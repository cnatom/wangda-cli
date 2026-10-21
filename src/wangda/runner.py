"""Persisted sequential supervisor with bounded, interruptible recovery."""
from copy import deepcopy
import json
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid

import psutil

from .adapter import validate_url
from .browser import Browser
from .config import load_config
from .state import Store, atomic_json, exclusive, scrub, timestamp

EXIT_CODES = {'completed': 0, 'stopped': 0, 'paused': 0, 'waiting_login': 3, 'unconfirmed': 4, 'failed': 1}
HEALTH_EVENTS = {'tick', 'course_start', 'subject', 'confirm_wait', 'course_done'}


def worker_command(config, url):
    return [sys.executable, '-m', 'wangda.worker', str(config.data_dir / 'run-config.json'), url]


class Runner:
    def __init__(self, config, worker_command=worker_command, browser=None, retry_delay=2):
        self.config = config
        self.store = Store(config.data_dir)
        self.worker_command = worker_command
        self.browser = browser if browser is not None else Browser(config)
        self.retry_delay = retry_delay
        self.child = None
        self.state = None

    def save(self):
        self.state['heartbeat_at'] = timestamp()
        self.store.write(self.state)

    def finish(self, status):
        self.stop_child()
        self.state['worker_pid'] = None
        self.state['worker'] = None
        self.state['status'] = status
        self.state['finished_at'] = timestamp()
        self.save()
        return EXIT_CODES[status]

    def stop_child(self):
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)
        self.browser.close()

    def cleanup_orphan(self, previous):
        """Recover only a proven worker left by a dead supervisor, under both locks."""
        if previous.get('status') != 'running':
            return
        worker = previous.get('worker') or {}
        try:
            process = psutil.Process(worker['pid'])
            expected = ['-m', 'wangda.worker', str(self.config.data_dir / 'run-config.json')]
            if (abs(process.create_time() - worker['created']) < 0.01
                    and process.cmdline()[1:4] == expected):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except (KeyError, psutil.NoSuchProcess):
            pass
        self.browser.close()

    def read_event(self, event, log_handle):
        event = scrub(event)
        log_handle.write(json.dumps(event, ensure_ascii=False) + '\n')
        log_handle.flush()
        self.state['last_event'] = event
        if event.get('ev') == 'tick':
            self.state['progress'] = {k: event.get(k) for k in ('course', 'idx', 'v', 'prog', 'stat', 'cnt')}
        self.save()

    def attempt(self, item, log_handle):
        messages = queue.Queue()
        self.child = subprocess.Popen(self.worker_command(self.config, item['url']),
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
        self.state['worker_pid'] = self.child.pid
        try:
            self.state['worker'] = {'pid': self.child.pid, 'created': psutil.Process(self.child.pid).create_time()}
        except psutil.NoSuchProcess:
            self.state['worker'] = None
        self.save()

        def consume():
            try:
                for line in self.child.stdout:
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict) and isinstance(event.get('ev'), str):
                            messages.put(event)
                    except (ValueError, TypeError):
                        # Never persist raw browser errors or unknown stdout.
                        continue
            finally:
                self.child.stdout.close()

        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        last_health = time.monotonic()
        result = None
        try:
            while True:
                action = self.store.command(self.state['run_id'])
                if action:
                    return 'paused' if action == 'pause' else 'stopped'
                exited = self.child.poll() is not None
                if exited:
                    reader.join(timeout=2)
                while True:
                    try:
                        event = messages.get_nowait()
                    except queue.Empty:
                        break
                    self.read_event(event, log_handle)
                    if event['ev'] in HEALTH_EVENTS:
                        last_health = time.monotonic()
                    if event['ev'] == 'result':
                        result = event
                if exited:
                    if result and result.get('status') in ('waiting_login', 'unconfirmed'):
                        return result['status']
                    if result and result.get('status') == 'completed' and result.get('verified') is True and self.child.returncode == 0:
                        item['result'] = result
                        return 'completed'
                    return 'failed' if self.child.returncode or (result and result.get('status') == 'failed') else 'unconfirmed'
                if time.monotonic() - last_health > self.config.stale_seconds:
                    self.state['reason'] = 'playback_heartbeat_timeout'
                    return 'failed'
                self.save()
                time.sleep(self.config.poll_seconds)
        finally:
            self.stop_child()
            reader.join(timeout=2)

    def run(self, urls=None, resume=False, run_id=None):
        with exclusive(self.config):
            previous = self.store.read()
            if resume:
                items = deepcopy(previous.get('queue', []))
                if not items:
                    raise ValueError('No saved queue to resume')
                for item in items:
                    validate_url(item['url'])
                    if item.get('status') != 'completed':
                        item['status'] = 'pending'
                        item['attempts'] = 0
            else:
                if not urls:
                    raise ValueError('At least one URL is required')
                urls = list(dict.fromkeys(validate_url(url) for url in urls))
                items = [{'url': url, 'status': 'pending', 'attempts': 0} for url in urls]
            self.cleanup_orphan(previous)
            identity = psutil.Process()
            self.state = {'schema_version': 1, 'run_id': run_id or uuid.uuid4().hex,
                          'status': 'running', 'queue': items, 'index': 0,
                          'owner': {'pid': identity.pid, 'created': identity.create_time()},
                          'started_at': timestamp(), 'config': self.config.as_dict()}
            self.save()
            atomic_json(self.config.data_dir / 'run-config.json', self.config.as_dict())
            log_dir = self.config.data_dir / 'logs'
            log_dir.mkdir(exist_ok=True, mode=0o700)
            old_handlers = {}
            if threading.current_thread() is threading.main_thread():
                def interrupted(*_):
                    raise KeyboardInterrupt()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    old_handlers[sig] = signal.signal(sig, interrupted)
            try:
                with (log_dir / f"events-{self.state['run_id']}.jsonl").open('a', encoding='utf-8') as log_handle:
                    for index, item in enumerate(items):
                        self.state['index'] = index
                        if item['status'] == 'completed':
                            continue
                        self.state.pop('progress', None)
                        for attempt in range(self.config.retries + 1):
                            item['attempts'] += 1
                            item['status'] = 'running'
                            self.save()
                            status = self.attempt(item, log_handle)
                            item['status'] = status
                            self.save()
                            if status == 'completed':
                                break
                            if status != 'failed' or attempt == self.config.retries:
                                return self.finish(status)
                            end = time.monotonic() + min(30, self.retry_delay * 2 ** attempt)
                            while time.monotonic() < end:
                                action = self.store.command(self.state['run_id'])
                                if action:
                                    return self.finish('paused' if action == 'pause' else 'stopped')
                                time.sleep(min(self.config.poll_seconds, max(0, end - time.monotonic())))
                    self.state['index'] = len(items)
                    return self.finish('completed')
            except KeyboardInterrupt:
                return self.finish('stopped')
            except Exception as error:
                self.state['reason'] = type(error).__name__
                self.finish('failed')
                raise
            finally:
                self.stop_child()
                self.state['worker_pid'] = None
                self.save()
                for sig, handler in old_handlers.items():
                    signal.signal(sig, handler)


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    config = load_config(env={}, **request['config'])
    return Runner(config).run(request.get('urls'), resume=request.get('resume', False), run_id=request['run_id'])


if __name__ == '__main__':
    raise SystemExit(main())
