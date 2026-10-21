"""Stable JSON command-line interface for humans and local-execution agents."""
import argparse
from collections import deque
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from filelock import Timeout
import psutil

from . import __version__, engine
from .adapter import LoginRequired, Unconfirmed, inspect, validate_url
from .browser import Browser, discover_browser
from .config import load_config
from .runner import Runner
from .state import Store, atomic_json, exclusive, scrub


def emit(value):
    print(json.dumps(scrub({'schema_version': 1, **value}), ensure_ascii=False), flush=True)


def owner_alive(state):
    owner = state.get('owner') or {}
    try:
        process = psutil.Process(owner['pid'])
        return process.is_running() and abs(process.create_time() - owner['created']) < 0.01
    except (KeyError, psutil.Error):
        return False


def snapshot(store):
    state = store.read()
    if state['status'] == 'running':
        state['owner_alive'] = owner_alive(state)
        if not state['owner_alive']:
            state['status'] = 'interrupted'
    return state


def add_common(parser):
    for name in ('config', 'data-dir', 'profile', 'browser'):
        parser.add_argument('--' + name, default=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, default=argparse.SUPPRESS)
    parser.add_argument('--json', action='store_true', default=argparse.SUPPRESS,
                        help='Explicit JSON mode (all command results are JSON by default)')


def parser():
    result = argparse.ArgumentParser(prog='wanda', description=__doc__)
    result.add_argument('--version', action='version', version=__version__)
    add_common(result)
    commands = result.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'login', 'inspect', 'run', 'resume', 'status', 'pause', 'stop', 'logs', 'skill-path'):
        sub = commands.add_parser(name)
        add_common(sub)
        if name == 'inspect':
            sub.add_argument('url')
        if name == 'run':
            sub.add_argument('urls', nargs='+')
        if name in ('run', 'resume'):
            sub.add_argument('--rate', type=float, default=None)
            sub.add_argument('--headed', action=argparse.BooleanOptionalAction, default=None)
            sub.add_argument('--retries', type=int, default=None)
            sub.add_argument('--background', action='store_true')
        if name in ('pause', 'stop'):
            sub.add_argument('--timeout', type=float, default=15)
        if name == 'logs':
            sub.add_argument('--tail', type=int, default=20)
    return result


def start_background(config, urls, resume):
    # Preflight without changing state. The runner acquires the same locks again.
    with exclusive(config):
        if resume and not Store(config.data_dir).read().get('queue'):
            raise ValueError('No saved queue to resume')
    run_id = uuid.uuid4().hex
    requests = config.data_dir / 'requests'
    requests.mkdir(exist_ok=True, mode=0o700)
    path = requests / f'{run_id}.json'
    atomic_json(path, {'config': config.as_dict(), 'urls': urls, 'resume': resume, 'run_id': run_id})
    options = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    proc = subprocess.Popen([sys.executable, '-m', 'wangda.runner', str(path)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = Store(config.data_dir).read()
        if state.get('run_id') == run_id:
            return state
        if proc.poll() is not None:
            raise RuntimeError('Background runner exited before claiming the queue (possibly another runner won the lock)')
        time.sleep(0.05)
    raise RuntimeError('Background runner did not acknowledge startup; inspect status before retrying')


def control(config, action, timeout):
    if not 0 < timeout <= 120:
        raise ValueError('timeout must be between 0 and 120 seconds')
    store = Store(config.data_dir)
    state = snapshot(store)
    if state['status'] != 'running':
        if action == 'stop':
            with exclusive(config):
                Runner(config).cleanup_orphan(store.read())
                Browser(config).close()
                state['status'] = 'stopped'
                state['worker'] = None
                state['worker_pid'] = None
                store.write(state)
        return state
    store.control(action, state['run_id'])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = snapshot(store)
        if state['status'] != 'running':
            return state
        time.sleep(0.1)
    raise RuntimeError('Control was requested but not yet acknowledged; inspect status before retrying')


def main(argv=None):
    args = parser().parse_args(argv)
    values = vars(args)
    overrides = {key: values.get(key) for key in ('data_dir', 'profile', 'browser', 'port', 'rate', 'headed', 'retries')}
    old_sink = engine.EVENT_SINK
    engine.EVENT_SINK = lambda event: print(json.dumps(scrub(event), ensure_ascii=False), file=sys.stderr, flush=True)
    try:
        config = load_config(config_file=values.get('config'), **overrides)
        store = Store(config.data_dir)
        if args.command == 'status':
            emit(snapshot(store))
        elif args.command == 'skill-path':
            bundled = Path(__file__).resolve().parent / 'skill' / 'SKILL.md'
            source = Path(__file__).resolve().parents[2] / 'skills' / 'wangda' / 'SKILL.md'
            path = bundled if bundled.is_file() else source
            if not path.is_file():
                raise FileNotFoundError('Bundled Agent Skill is missing; reinstall wangda-cli')
            emit({'status': 'ok', 'path': str(path)})
        elif args.command == 'doctor':
            try:
                browser_path = discover_browser(config.browser)
                browser_error = None
            except FileNotFoundError:
                browser_path, browser_error = None, 'Install Chrome/Chromium or set WANDA_BROWSER'
            dependencies = {name: importlib.metadata.version(name) for name in
                            ('websocket-client', 'platformdirs', 'psutil', 'filelock')}
            emit({'status': 'ready' if browser_path else 'missing_browser', 'version': __version__,
                  'browser': browser_path, 'detail': browser_error, 'config': config.as_dict(),
                  'dependencies': dependencies})
            return 0 if browser_path else 1
        elif args.command == 'login':
            with exclusive(config):
                browser = Browser(config)
                browser.open(headed=True)
                page = browser.page()
                try:
                    page.goto(engine.HOST + '/')
                finally:
                    page.close()
                emit({'status': 'waiting_login', 'detail': 'Complete login yourself in the dedicated window, then run/resume. Use stop to close it.'})
        elif args.command == 'inspect':
            validate_url(args.url)
            with exclusive(config):
                data = inspect(Browser(config), config, args.url)
                emit({'status': 'inspected', 'data': data})
        elif args.command in ('run', 'resume'):
            resume = args.command == 'resume'
            urls = None if resume else [validate_url(url) for url in args.urls]
            if resume:
                saved = store.read()
                if not saved.get('queue'):
                    raise ValueError('No saved queue to resume')
                if saved.get('config'):
                    previous = {**saved['config'], **{key: value for key, value in overrides.items() if value is not None}}
                    config = load_config(env={}, **previous)
            if args.background:
                state = start_background(config, urls, resume)
                emit(state)
                return 0
            code = Runner(config).run(urls, resume=resume)
            emit(Store(config.data_dir).read())
            return code
        elif args.command in ('pause', 'stop'):
            emit(control(config, args.command, args.timeout))
        elif args.command == 'logs':
            if not 1 <= args.tail <= 10000:
                raise ValueError('tail must be 1..10000')
            state = store.read()
            run_id = state.get('run_id')
            # Run ids are generated UUID hex; never accept arbitrary file paths from a snapshot.
            if run_id and (len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id)):
                raise ValueError('Invalid saved run id')
            path = config.data_dir / 'logs' / f'events-{run_id}.jsonl'
            events = []
            if run_id and path.exists():
                with path.open(encoding='utf-8') as handle:
                    for line in deque(handle, maxlen=args.tail):
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            pass
            emit({'status': 'ok', 'run_id': run_id, 'events': events})
        return 0
    except Timeout:
        emit({'status': 'busy', 'detail': 'A runner or browser operation owns this data directory/profile'})
        return 5
    except LoginRequired:
        emit({'status': 'waiting_login', 'detail': 'Run wanda login and authenticate yourself'})
        return 3
    except Unconfirmed:
        emit({'status': 'unconfirmed', 'detail': 'The platform did not expose a confirmed result'})
        return 4
    except (ValueError, FileNotFoundError) as error:
        emit({'status': 'error', 'detail': str(error)})
        return 2
    except Exception as error:
        # Raw remote exceptions may contain authentication data.
        emit({'status': 'failed', 'reason': type(error).__name__})
        return 1
    finally:
        engine.EVENT_SINK = old_sink
