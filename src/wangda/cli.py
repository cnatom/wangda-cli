"""Stable JSON command-line interface for humans and local-execution agents."""
import argparse
from collections import deque
import datetime
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

from . import __version__, adapter, auth, durations, engine
from .adapter import (CertificateUnavailable, LoginRequired, Unconfirmed, browser_login,
                      claim_certificate, inspect, plan, validate_url)
from .browser import Browser, discover_browser
from .config import load_config
from .runner import Runner
from .state import Store, atomic_json, exclusive, scrub

RUNNER_CREATIONFLAGS = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def emit(value):
    print(json.dumps(scrub({'schema_version': 1, **value}), ensure_ascii=False), flush=True)


def owner_alive(state):
    owner = state.get('owner') or {}
    try:
        process = psutil.Process(owner['pid'])
        return process.is_running() and abs(process.create_time() - owner['created']) < 0.01
    except (KeyError, psutil.Error):
        return False


def read_events(data_dir, state, tail):
    """Recent events of the current run; used by `logs` and by the status ETA."""
    run_id = state.get('run_id')
    # Run ids are generated UUID hex; never accept arbitrary file paths from a snapshot.
    if not run_id or len(run_id) != 32 or any(c not in '0123456789abcdef' for c in run_id):
        return []
    path = data_dir / 'logs' / f'events-{run_id}.jsonl'
    if not path.exists():
        return []
    events = []
    with path.open(encoding='utf-8') as handle:
        for line in deque(handle, maxlen=tail):
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
    return events


def course_spans(events):
    """Observed wall-clock seconds per finished course, from course_start -> course_done."""
    starts, spans = {}, []
    for event in events:
        name, course, moment = event.get('ev'), event.get('course'), event.get('t')
        if not course or not isinstance(moment, (int, float)):
            continue
        if name == 'course_start':
            starts[course] = moment
        elif name == 'course_done' and course in starts:
            spans.append(moment - starts.pop(course))
    return spans


def eta_of(state, events, progress, cache=None):
    """Remaining wall-clock time: exact lengths where recorded, the run's own pace elsewhere."""
    cache = cache or {}
    queue = state.get('queue') or []
    pending = [item for item in queue if item.get('status') in ('pending', 'paused')]
    current = progress.get('current') or {}
    saved_rate = (state.get('config') or {}).get('rate')
    position, duration = current.get('position'), current.get('duration')
    rate = current.get('rate') or saved_rate or 1.0
    left_now = max(0.0, (duration - position) / rate) if isinstance(position, (int, float)) and duration else 0.0
    known, unknown = 0.0, 0
    for item in pending:
        _, course = engine.parse_url(item.get('url') or '')
        value = durations.seconds_for(None, course, cache) if course else None
        if value:
            known += value
        else:
            unknown += 1
    known_at_rate = known / rate if rate else known
    spans = course_spans(events)
    average = sum(spans) / len(spans) if spans else None
    if not spans and not left_now and not known:
        return None
    eta = left_now + known_at_rate + (average * unknown if average else 0.0)
    basis = 'measured_durations' if known and not unknown else (
        'measured_plus_pace' if known else ('observed_pace' if average else 'current_course_only'))
    block = {'eta_seconds': int(round(eta)), 'remaining_courses': progress['pending'],
             'known_courses': len(pending) - unknown, 'unknown_courses': unknown,
             'known_seconds_at_rate': int(round(known_at_rate)), 'basis': basis}
    if average:
        block['seconds_per_course'] = int(round(average))
        block['sample'] = len(spans)
    if eta:
        finish = datetime.datetime.now().astimezone() + datetime.timedelta(seconds=eta)
        block['eta_at'] = finish.isoformat(timespec='minutes')
    return block


def progress_of(state, events=None, cache=None):
    """One-glance progress: counts, the course being played, and whether login is needed."""
    queue = state.get('queue') or []
    counts = {}
    for item in queue:
        name = item.get('status') or 'unknown'
        counts[name] = counts.get(name, 0) + 1
    total = len(queue)
    done = counts.get('completed', 0)
    block = {'completed': done, 'total': total, 'pending': counts.get('pending', 0),
             'running': counts.get('running', 0), 'unconfirmed': counts.get('unconfirmed', 0),
             'failed': counts.get('failed', 0),
             'percent': round(done * 100.0 / total, 1) if total else 0.0}
    current = next((item for item in queue if item.get('status') == 'running'), None)
    if current:
        last = state.get('last_event') or {}
        view = last.get('v') or {}
        url = current.get('url') or ''
        course = (url.split('/subject-course/')[-1].split('/')[0]
                  if '/subject-course/' in url else url.rsplit('/', 1)[-1])
        block['current'] = {'course': course, 'url': url,
                            'position': view.get('cur'), 'duration': view.get('dur'),
                            'rate': view.get('rate'), 'sections': last.get('prog')}
    if state.get('pass'):
        block['pass'] = state['pass']
    if state.get('session_note'):
        block['session_note'] = state['session_note']
    if events is not None:
        block['eta'] = eta_of(state, events, block, cache)
    return block


def snapshot(store, events=None, cache=None):
    state = store.read()
    if state['status'] == 'running':
        state['owner_alive'] = owner_alive(state)
        if not state['owner_alive']:
            state['status'] = 'interrupted'
    state['progress'] = progress_of(state, events, cache)
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
    for name in ('doctor', 'login', 'auth', 'inspect', 'plan', 'certificate', 'run', 'resume', 'status', 'pause', 'stop',
                 'logs', 'skill-path'):
        sub = commands.add_parser(name)
        add_common(sub)
        if name == 'auth':
            sub.add_argument('--username', default=None,
                             help='Employee id or phone number; prompted when omitted')
            sub.add_argument('--probe', action='store_true',
                             help='Only read the public key and sign endpoint; never sends an SMS')
            sub.add_argument('--code-stdin', action='store_true',
                             help='Read the SMS code from stdin instead of a no-echo prompt')
        if name == 'inspect':
            sub.add_argument('url')
        if name == 'plan':
            sub.add_argument('urls', nargs='+')
            sub.add_argument('--rate', type=float, default=1.5)
        if name == 'certificate':
            sub.add_argument('url')
            sub.add_argument('--download', metavar='DIR', default=None)
            sub.add_argument('--headed', action=argparse.BooleanOptionalAction, default=None)
        if name == 'run':
            sub.add_argument('urls', nargs='+')
        if name in ('run', 'resume'):
            sub.add_argument('--rate', type=float, default=None)
            sub.add_argument('--plan-durations', action=argparse.BooleanOptionalAction, default=None,
                             help='Read every course length before playback (default on)')
            sub.add_argument('--refresh-durations', action='store_true',
                             help='Ignore the duration cache and read the pages again')
            sub.add_argument('--headed', action=argparse.BooleanOptionalAction, default=None)
            sub.add_argument('--retries', type=int, default=None)
            sub.add_argument('--continue-on-error', action=argparse.BooleanOptionalAction, default=None)
            sub.add_argument('--watch', action=argparse.BooleanOptionalAction, default=None,
                             help='Keep re-checking and re-running until every entry is confirmed complete')
            sub.add_argument('--watch-interval', type=float, default=None)
            sub.add_argument('--background', action='store_true')
        if name == 'login':
            sub.add_argument('--timeout', type=float, default=600,
                             help='Seconds to wait for the manual login in the dedicated window')
        if name in ('pause', 'stop'):
            sub.add_argument('--timeout', type=float, default=15)
        if name == 'logs':
            sub.add_argument('--tail', type=int, default=20)
    return result


def planned_course_urls(config, urls):
    """Expand subject URLs into the course URLs this run will actually play."""
    result = []
    browser = None
    for url in urls:
        subject, course = engine.parse_url(url)
        if course:
            result.append(url)
            continue
        if not subject:
            continue
        browser = browser or Browser(config)
        data = inspect(browser, config, url)
        for item in data.get('items') or []:
            if item.get('type') != adapter.VIDEO_ITEM or item.get('opt'):
                continue
            if (item.get('st') or '').strip().startswith('已完成'):
                continue
            result.append(engine.course_url(item['id'], subject))
    return result


def prefetch_durations(config, urls, rate, refresh=False):
    """Read each course's own 「课程总时长」 before playback; cached values are reused forever."""
    cache = durations.load(config.data_dir)
    targets = []
    for url in planned_course_urls(config, urls):
        _, course = engine.parse_url(url)
        if course and (refresh or not durations.seconds_for(None, course, cache)):
            targets.append(url)
    if not targets:
        emit({'status': 'ok', 'detail': 'duration prefetch: nothing to fetch', 'cached': len(cache)})
        return
    data = plan(Browser(config), config, targets, rate=rate)
    for item in data['courses']:
        durations.remember(config.data_dir, item['course'], item['seconds'])
    emit({'status': 'ok', 'detail': 'duration prefetch',
          'fetched': len(data['courses']), 'missing': len(data['missing']),
          'total_seconds_at_rate': data['total_seconds_at_rate']})


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
        'creationflags': RUNNER_CREATIONFLAGS}
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
            try:
                # The final snapshot can be visible just before the runner's finally releases locks.
                with exclusive(config):
                    return state
            except Timeout:
                pass
        time.sleep(0.1)
    raise RuntimeError('Control was requested but not yet acknowledged; inspect status before retrying')


def main(argv=None):
    args = parser().parse_args(argv)
    values = vars(args)
    overrides = {key: values.get(key) for key in ('data_dir', 'profile', 'browser', 'port', 'rate',
                                                  'headed', 'retries', 'continue_on_error',
                                                  'watch', 'watch_interval', 'plan_durations')}
    old_sink = engine.EVENT_SINK
    engine.EVENT_SINK = lambda event: print(json.dumps(scrub(event), ensure_ascii=False), file=sys.stderr, flush=True)
    try:
        config = load_config(config_file=values.get('config'), **overrides)
        store = Store(config.data_dir)
        if args.command == 'status':
            emit(snapshot(store, events=read_events(config.data_dir, store.read(), 5000),
                          cache=durations.load(config.data_dir)))
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
                            ('websocket-client', 'platformdirs', 'psutil', 'filelock', 'cryptography')}
            try:
                saved = auth.read_session(config.data_dir / auth.SESSION_FILE)
                remaining = None
                if saved and isinstance(saved.get('expires_in'), (int, float)) and saved.get('obtained_at'):
                    remaining = int(saved['obtained_at'] + saved['expires_in'] - time.time())
                session = {'present': bool(saved), 'fresh': bool(saved and auth.is_fresh(saved)),
                           'expires_in_remaining': remaining}
            except auth.AuthError:
                session = {'present': True, 'fresh': False, 'detail': 'session file permissions are too open'}
            emit({'status': 'ready' if browser_path else 'missing_browser', 'version': __version__,
                  'browser': browser_path, 'detail': browser_error, 'config': config.as_dict(),
                  'session': session, 'dependencies': dependencies})
            return 0 if browser_path else 1
        elif args.command == 'auth':
            transport = auth.Transport(engine.HOST)
            if args.probe:
                emit({'status': 'ok', 'probe': auth.probe(transport)})
                return 0
            username = args.username or input('account (employee id or phone): ').strip()
            ask = ((lambda phone: input(f'verification code sent to {phone}: ').strip())
                   if args.code_stdin else auth.prompt_code)
            session = auth.authenticate(transport, username, ask)
            path = auth.write_private_json(config.data_dir / auth.SESSION_FILE, session)
            emit({'status': 'ready', 'username': auth.mask_phone(username),
                  'expires_in': session['expires_in'], 'session': str(path)})
        elif args.command == 'login':
            with exclusive(config):
                session = browser_login(config, timeout=args.timeout)
                emit({'status': 'ready', 'source': 'browser',
                      'expires_in': session['expires_in'],
                      'session': str(config.data_dir / auth.SESSION_FILE)})
        elif args.command == 'plan':
            urls = [validate_url(url) for url in args.urls]
            if args.rate not in (1.0, 1.2, 1.5):
                raise ValueError('rate must be one of 1.0, 1.2, 1.5')
            with exclusive(config):
                emit({'status': 'ok', 'data': plan(Browser(config), config, urls, rate=args.rate)})
        elif args.command == 'inspect':
            validate_url(args.url)
            with exclusive(config):
                data = inspect(Browser(config), config, args.url)
                emit({'status': 'inspected', 'data': data})
        elif args.command == 'certificate':
            validate_url(args.url)
            with exclusive(config):
                emit(claim_certificate(Browser(config), config, args.url, download_dir=args.download))
        elif args.command in ('run', 'resume'):
            resume = args.command == 'resume'
            urls = None if resume else [validate_url(url) for url in args.urls]
            if resume:
                saved = store.read()
                if not saved.get('queue'):
                    raise ValueError('No saved queue to resume')
                if saved.get('config'):
                    config = load_config(config_file=values.get('config'), base=saved['config'], **overrides)
            if not resume and config.plan_durations:
                with exclusive(config):
                    prefetch_durations(config, urls, args.rate or config.rate)
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
            emit({'status': 'ok', 'run_id': state.get('run_id'),
                  'events': read_events(config.data_dir, state, args.tail)})
        return 0
    except Timeout:
        emit({'status': 'busy', 'detail': 'A runner or browser operation owns this data directory/profile'})
        return 5
    except LoginRequired:
        emit({'status': 'waiting_login', 'detail': 'Run wanda login and authenticate yourself'})
        return 3
    except CertificateUnavailable as error:
        emit({'status': error.status, 'detail': error.detail})
        return 4
    except Unconfirmed:
        emit({'status': 'unconfirmed', 'detail': 'The platform did not expose a confirmed result'})
        return 4
    except (ValueError, FileNotFoundError) as error:
        emit({'status': 'error', 'detail': str(error)})
        return 2
    except auth.AuthError as error:
        emit({'status': 'failed', 'detail': str(error)})
        return 1
    except Exception as error:
        # Raw remote exceptions may contain authentication data.
        emit({'status': 'failed', 'reason': type(error).__name__})
        return 1
    finally:
        engine.EVENT_SINK = old_sink
