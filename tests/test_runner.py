import json
import os
import subprocess
import sys
import pytest
from wangda.config import load_config
from wangda.state import Store
from wangda.runner import WORKER_CREATIONFLAGS, Runner

URL_A = 'https://wangda.chinamobile.com/#/study/subject/detail/demo-a/1'
URL_B = 'https://wangda.chinamobile.com/#/study/subject/detail/demo-b/1'


class NoBrowser:
    def __init__(self):
        self.closed = 0
    def close(self):
        self.closed += 1


def command(script):
    return [sys.executable, '-u', '-c', script]


def test_persisted_queue_completes_sequentially_and_requires_result(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, env={})
    seen = []
    def worker(config, url):
        seen.append(url)
        return command('import json; print(json.dumps({"ev":"result", "status":"completed", "verified":True}))')
    browser = NoBrowser()
    assert Runner(cfg, worker_command=worker, browser=browser).run([URL_A, URL_B]) == 0
    state = Store(tmp_path).read()
    assert state['status'] == 'completed'
    assert [item['status'] for item in state['queue']] == ['completed', 'completed']
    assert seen == [URL_A, URL_B]
    assert browser.closed >= 1


def test_exit_zero_without_completion_is_unconfirmed_not_success(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0, env={})
    rc = Runner(cfg, worker_command=lambda *_: command('pass'), browser=NoBrowser()).run([URL_A])
    assert rc == 4
    assert Store(tmp_path).read()['status'] == 'unconfirmed'


def test_login_stops_without_retries_or_starting_next_url(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, env={})
    seen = []
    def worker(config, url):
        seen.append(url)
        return command('print(\'{"ev":"result","status":"waiting_login"}\')')
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A, URL_B]) == 3
    state = Store(tmp_path).read()
    assert state['status'] == 'waiting_login'
    assert state['index'] == 0
    assert seen == [URL_A]


def test_watchdog_has_bounded_retries_even_if_error_lines_refresh(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, stale_seconds=0.1, retries=1, env={})
    def worker(*_):
        return command('import time;\nwhile True:\n print(\'{"ev":"cdp_error"}\',flush=True); time.sleep(.01)')
    assert Runner(cfg, worker_command=worker, browser=NoBrowser(), retry_delay=0).run([URL_A]) == 1
    state = Store(tmp_path).read()
    assert state['queue'][0]['attempts'] == 2
    assert state['status'] == 'failed'


def test_resume_skips_completed_queue_entries_and_keeps_current_index(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, env={})
    store = Store(tmp_path)
    store.write({'status': 'paused', 'queue': [{'url': URL_A, 'status': 'completed', 'attempts': 1},
                                            {'url': URL_B, 'status': 'pending', 'attempts': 0}], 'index': 1})
    seen = []
    def worker(config, url):
        seen.append(url)
        return command('print(\'{"ev":"result","status":"completed","verified":true}\')')
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run(resume=True) == 0
    assert seen == [URL_B]


def test_stop_command_is_acknowledged_and_child_reaped(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, env={})
    script = ('import json,time,pathlib; '
              f'p=pathlib.Path({str(tmp_path)!r}); '
              's=json.loads((p/"state.json").read_text()); '
              '(p/"control.json").write_text(json.dumps({"run_id":s["run_id"],"action":"stop"})); '
              'time.sleep(30)')
    runner = Runner(cfg, worker_command=lambda *_: command(script), browser=NoBrowser())
    assert runner.run([URL_A]) == 0
    assert Store(tmp_path).read()['status'] == 'stopped'
    assert runner.child.poll() is not None


def test_resume_without_queue_is_rejected_before_browser_use(tmp_path):
    cfg = load_config(data_dir=tmp_path, env={})
    with pytest.raises(ValueError):
        Runner(cfg, browser=NoBrowser()).run(resume=True)


def test_worker_output_is_utf8_even_when_parent_locale_is_not(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, env={})
    script = ('import json; '
              'print(json.dumps({"ev":"subject","prog":"完成 0 项 / 共 1 项"}, ensure_ascii=False), flush=True); '
              'print(json.dumps({"ev":"result","status":"completed","verified":True}), flush=True)')
    assert Runner(cfg, worker_command=lambda *_: command(script), browser=NoBrowser()).run([URL_A]) == 0
    state = Store(tmp_path).read()
    events = [json.loads(line) for line in
              (tmp_path / 'logs' / f"events-{state['run_id']}.jsonl").read_text(encoding='utf-8').splitlines()]
    subject = next(event for event in events if event['ev'] == 'subject')
    assert subject['prog'] == '完成 0 项 / 共 1 项'


def test_worker_creationflags_hide_console_on_windows():
    if os.name != 'nt':
        pytest.skip('Windows-only console flag')
    assert WORKER_CREATIONFLAGS & subprocess.CREATE_NO_WINDOW


def test_continue_on_error_attempts_remaining_items_and_reports_partial(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0,
                      continue_on_error=True, env={})
    seen = []
    def worker(config, url):
        seen.append(url)
        status = 'completed' if url == URL_B else 'unconfirmed'
        script = ('import json; print(json.dumps({"ev":"result","status":"%s","verified":%s}), flush=True)'
                  % (status, 'True' if status == 'completed' else 'False'))
        return command(script)
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A, URL_B]) == 4
    state = Store(tmp_path).read()
    assert [item['status'] for item in state['queue']] == ['unconfirmed', 'completed']
    assert seen == [URL_A, URL_B]
    assert state['status'] == 'unconfirmed'


def test_continue_on_error_keeps_going_after_failed_item(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0,
                      continue_on_error=True, env={})
    seen = []
    def worker(config, url):
        seen.append(url)
        status = 'completed' if url == URL_B else 'failed'
        script = ('import json; print(json.dumps({"ev":"result","status":"%s","verified":%s}), flush=True)'
                  % (status, 'True' if status == 'completed' else 'False'))
        return command(script)
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A, URL_B]) == 1
    state = Store(tmp_path).read()
    assert [item['status'] for item in state['queue']] == ['failed', 'completed']
    assert seen == [URL_A, URL_B]
    assert state['status'] == 'failed'


def test_without_continue_on_error_unconfirmed_stops_the_queue(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0, env={})
    seen = []
    def worker(config, url):
        seen.append(url)
        return command('print(\'{"ev":"result","status":"unconfirmed","verified":false}\')')
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A, URL_B]) == 4
    assert seen == [URL_A]
    state = Store(tmp_path).read()
    assert [item['status'] for item in state['queue']] == ['unconfirmed', 'pending']


def test_continue_on_error_still_stops_for_login(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0,
                      continue_on_error=True, env={})
    seen = []
    def worker(config, url):
        seen.append(url)
        return command('print(\'{"ev":"result","status":"waiting_login","verified":false}\')')
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A, URL_B]) == 3
    assert seen == [URL_A]
    state = Store(tmp_path).read()
    assert state['status'] == 'waiting_login'



def test_watch_keeps_retrying_until_every_entry_is_complete(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0, watch=True,
                      watch_interval=0.01, watch_max_passes=3, env={})
    calls = []

    def worker(config, url):
        calls.append(url)
        status = 'unconfirmed' if len(calls) == 1 else 'completed'
        verified = 'True' if status == 'completed' else 'False'
        return command(f'import json; print(json.dumps({{"ev":"result","status":"{status}","verified":{verified}}}))')

    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A]) == 0
    state = Store(tmp_path).read()
    assert state['status'] == 'completed'
    assert [item['status'] for item in state['queue']] == ['completed']
    assert calls == [URL_A, URL_A]
    assert state['pass'] == 2


def test_watch_is_bounded_by_max_passes(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0, watch=True,
                      watch_interval=0.01, watch_max_passes=2, env={})
    calls = []

    def worker(config, url):
        calls.append(url)
        return command('import json; print(json.dumps({"ev":"result","status":"unconfirmed","verified":False}))')

    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A]) == 4
    assert Store(tmp_path).read()['status'] == 'unconfirmed'
    assert len(calls) == 2


def test_watch_waits_for_a_new_token_instead_of_finishing(tmp_path, monkeypatch):
    import threading
    from wangda import auth
    monkeypatch.setattr(auth, 'verify_session', lambda session, **kw: 'expired')
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.05, retries=0, watch=True,
                      watch_interval=0.01, watch_max_passes=3, session_wait_seconds=5, env={})

    def session(token, obtained_at):
        auth.write_private_json(tmp_path / auth.SESSION_FILE,
                                {'access_token': token, 'token_type': 'Bearer',
                                 'expires_in': 3600, 'obtained_at': obtained_at})

    session('old-token', 0)   # expired: the pass must stop before the worker runs

    def reauth():
        import time as _time
        _time.sleep(0.3)
        session('new-token', int(_time.time()))

    calls = []

    def worker(config, url):
        calls.append(url)
        return command('import json; print(json.dumps({"ev":"result","status":"completed","verified":True}))')

    threading.Thread(target=reauth, daemon=True).start()
    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A]) == 0
    assert calls == [URL_A]
    assert Store(tmp_path).read()['status'] == 'completed'


def test_watch_without_a_session_file_does_not_hang_on_login_wall(tmp_path):
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, retries=0, watch=True,
                      watch_interval=0.01, session_wait_seconds=5, env={})
    calls = []

    def worker(config, url):
        calls.append(url)
        return command('import json; print(json.dumps({"ev":"result","status":"waiting_login"}))')

    assert Runner(cfg, worker_command=worker, browser=NoBrowser()).run([URL_A]) == 3
    assert len(calls) == 1


def _runner_with_session(tmp_path, age):
    import time as _time
    from wangda import auth
    cfg = load_config(data_dir=tmp_path, poll_seconds=0.01, env={})
    session = {'access_token': 'tok', 'token_type': 'Bearer',
               'expires_in': auth.DEFAULT_EXPIRES_IN, 'obtained_at': int(_time.time()) - age}
    auth.write_private_json(tmp_path / auth.SESSION_FILE, session)
    return cfg


def test_expired_session_is_kept_when_the_platform_still_accepts_it(tmp_path, monkeypatch):
    """声明的 4 小时到了不等于平台作废：先问服务端，别急着停在等登录。"""
    from wangda import auth
    cfg = _runner_with_session(tmp_path, age=auth.DEFAULT_EXPIRES_IN + 600)
    runner = Runner(cfg, worker_command=lambda c, u: command('pass'), browser=NoBrowser())
    monkeypatch.setattr(auth, 'verify_session', lambda session, **kw: 'ok')
    assert runner.session_usable() is True
    assert Store(tmp_path).read()['session_note'] == 'declared_expired_but_accepted'


def test_expired_session_stops_the_queue_when_the_platform_rejects_it(tmp_path, monkeypatch):
    from wangda import auth
    cfg = _runner_with_session(tmp_path, age=auth.DEFAULT_EXPIRES_IN + 600)
    runner = Runner(cfg, worker_command=lambda c, u: command('pass'), browser=NoBrowser())
    monkeypatch.setattr(auth, 'verify_session', lambda session, **kw: 'expired')
    assert runner.session_usable() is False


def test_unreachable_probe_does_not_stop_the_queue(tmp_path, monkeypatch):
    """探针问不到答案时不能武断停下：真过期的话，下一次页面加载会直接露出登录墙。"""
    from wangda import auth
    cfg = _runner_with_session(tmp_path, age=auth.DEFAULT_EXPIRES_IN + 600)
    runner = Runner(cfg, worker_command=lambda c, u: command('pass'), browser=NoBrowser())
    monkeypatch.setattr(auth, 'verify_session', lambda session, **kw: 'unknown')
    assert runner.session_usable() is True
    assert 'session_note' not in Store(tmp_path).read()


def test_fresh_session_needs_no_probe(tmp_path, monkeypatch):
    from wangda import auth
    cfg = _runner_with_session(tmp_path, age=10)
    runner = Runner(cfg, worker_command=lambda c, u: command('pass'), browser=NoBrowser())
    def boom(*a, **kw):
        raise AssertionError('fresh sessions must not be probed')
    monkeypatch.setattr(auth, 'verify_session', boom)
    assert runner.session_usable() is True
