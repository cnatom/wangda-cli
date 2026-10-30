import json
import os
import subprocess
import sys
from unittest.mock import patch

from wangda.adapter import CertificateUnavailable
from wangda.state import Store
from wangda.cli import RUNNER_CREATIONFLAGS, main


def test_status_is_json_and_does_not_create_profile_or_connect(tmp_path, capsys):
    with patch('wangda.cli.Browser') as browser:
        assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
        browser.assert_not_called()
    assert json.loads(capsys.readouterr().out)['status'] == 'idle'
    assert not (tmp_path / 'profile').exists()


def test_parse_options_before_and_after_command(tmp_path, capsys):
    assert main(['--data-dir', str(tmp_path), 'status', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'idle'


def test_invalid_url_returns_json_error_without_browser(tmp_path, capsys):
    with patch('wangda.cli.Browser') as browser:
        assert main(['run', 'https://example.test/', '--data-dir', str(tmp_path)]) == 2
        browser.assert_not_called()
    assert json.loads(capsys.readouterr().out)['status'] == 'error'


def test_running_task_refuses_inspect_and_login(tmp_path, capsys):
    from filelock import FileLock
    from wangda.config import load_config
    cfg = load_config(data_dir=tmp_path, env={})
    with FileLock(str(cfg.data_dir / 'runner.lock')):
        assert main(['login', '--data-dir', str(tmp_path)]) == 5
    assert json.loads(capsys.readouterr().out)['status'] == 'busy'


def test_resume_without_saved_queue_is_json_error(tmp_path, capsys):
    assert main(['resume', '--data-dir', str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'error'


def test_dead_owner_is_reported_interrupted_without_writing_state(tmp_path, capsys):
    store = Store(tmp_path)
    store.write({'status': 'running', 'owner': {'pid': 999999999, 'created': 0}, 'queue': []})
    before = (tmp_path / 'state.json').read_bytes()
    assert main(['status', '--data-dir', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'interrupted'
    assert before == (tmp_path / 'state.json').read_bytes()


def test_real_entry_point_has_no_agent_dependency(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('WANDA_', 'HERMES_'))}
    env['WANDA_DATA_DIR'] = str(tmp_path)
    result = subprocess.run([sys.executable, '-m', 'wangda', 'status', '--json'],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['schema_version'] == 1


def test_skill_path_points_to_portable_skill(capsys):
    from pathlib import Path
    assert main(['skill-path']) == 0
    result = json.loads(capsys.readouterr().out)
    content = Path(result['path']).read_text(encoding='utf-8')
    assert content.startswith('---\nname: wangda\n')
    assert '.hermes/' not in content


def test_pause_ack_waits_until_runner_releases_its_locks(tmp_path):
    from contextlib import contextmanager
    from filelock import Timeout
    from wangda.cli import control
    from wangda.config import load_config
    calls = []
    states = iter([{'status': 'running', 'run_id': 'test'}, {'status': 'paused'}])
    last = [{'status': 'paused'}]
    def current(_):
        last[0] = next(states, last[0])
        return last[0]
    @contextmanager
    def cleanup_lock(_):
        calls.append(1)
        if len(calls) == 1:
            raise Timeout('runner is still releasing resources')
        yield
    with patch('wangda.cli.snapshot', side_effect=current), patch('wangda.cli.exclusive', cleanup_lock), \
         patch('time.sleep'):
        assert control(load_config(data_dir=tmp_path, env={}), 'pause', 1)['status'] == 'paused'
    assert len(calls) == 2


CERT_SUBJECT = 'https://wangda.chinamobile.com/#/study/subject/detail/demo-topic/1'


def test_certificate_command_emits_result_and_passes_download_dir(tmp_path, capsys):
    target = tmp_path / 'cert.png'
    with patch('wangda.cli.Browser') as browser, \
         patch('wangda.cli.claim_certificate', return_value={'status': 'claimed', 'subject': 'demo-topic',
                                                             'downloaded': True, 'file': str(target)}) as claim:
        assert main(['certificate', CERT_SUBJECT, '--download', str(tmp_path),
                     '--data-dir', str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'claimed'
    assert result['file'] == str(target)
    assert claim.call_args.kwargs['download_dir'] == str(tmp_path)
    browser.assert_called_once()


def test_certificate_not_eligible_returns_exit_4_and_keeps_status(tmp_path, capsys):
    error = CertificateUnavailable('not_eligible', 'Certificate requirements are not met')
    with patch('wangda.cli.Browser'), patch('wangda.cli.claim_certificate', side_effect=error):
        assert main(['certificate', CERT_SUBJECT, '--data-dir', str(tmp_path)]) == 4
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'not_eligible'
    assert result['detail'] == 'Certificate requirements are not met'


def test_certificate_invalid_url_returns_error_without_browser(tmp_path, capsys):
    with patch('wangda.cli.Browser') as browser:
        assert main(['certificate', 'https://example.test/', '--data-dir', str(tmp_path)]) == 2
        browser.assert_not_called()
    assert json.loads(capsys.readouterr().out)['status'] == 'error'


def test_auth_probe_is_read_only_json_and_never_sends_sms(tmp_path, capsys):
    with patch('wangda.cli.auth.Transport') as transport:
        transport.return_value = transport
        with patch('wangda.cli.auth.probe', return_value={'public_key_sha256': 'abc', 'sign_present': True}):
            assert main(['auth', '--probe', '--data-dir', str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'ok'
    assert result['probe']['sign_present'] is True
    assert not (tmp_path / 'session.json').exists()


def test_auth_login_failure_is_reported_without_leaking_the_code(tmp_path, capsys, monkeypatch):
    from wangda.auth import AuthError
    monkeypatch.setattr('builtins.input', lambda prompt='': '123456')
    with patch('wangda.cli.auth.Transport'), \
            patch('wangda.cli.auth.authenticate', side_effect=AuthError('members-encrypt failed: errorCode 90134')):
        assert main(['auth', '--username', '13800000000', '--code-stdin', '--data-dir', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert json.loads(out)['status'] == 'failed'
    assert '123456' not in out


def test_runner_creationflags_hide_console_on_windows():
    if os.name != 'nt':
        return
    assert RUNNER_CREATIONFLAGS & subprocess.CREATE_NO_WINDOW
    assert RUNNER_CREATIONFLAGS & subprocess.CREATE_NEW_PROCESS_GROUP


def test_status_carries_a_one_glance_progress_block(tmp_path, capsys):
    store = Store(tmp_path)
    store.write({'status': 'running', 'run_id': 'a' * 32, 'pass': 1,
                 'session_note': 'declared_expired_but_accepted',
                 'last_event': {'ev': 'tick', 'prog': '完成 4 节/共 5 节',
                                'v': {'cur': 421, 'dur': 900, 'rate': 1.5}},
                 'queue': [
                     {'url': 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/c1/6/s1',
                      'status': 'completed'},
                     {'url': 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/c2/6/s1',
                      'status': 'running'},
                     {'url': 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/c3/6/s1',
                      'status': 'unconfirmed'},
                     {'url': 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/c4/6/s1',
                      'status': 'pending'}]})
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    progress = data['progress']
    assert (progress['completed'], progress['total'], progress['percent']) == (1, 4, 25.0)
    assert (progress['running'], progress['unconfirmed'], progress['pending']) == (1, 1, 1)
    assert progress['current']['course'] == 'c2'
    assert progress['current']['position'] == 421
    assert progress['current']['sections'] == '完成 4 节/共 5 节'
    assert progress['session_note'] == 'declared_expired_but_accepted'
    assert progress['pass'] == 1


def test_idle_status_reports_zero_progress(tmp_path, capsys):
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    progress = json.loads(capsys.readouterr().out)['progress']
    assert {k: v for k, v in progress.items() if k != 'eta'} == {
        'completed': 0, 'total': 0, 'pending': 0, 'running': 0,
        'unconfirmed': 0, 'failed': 0, 'percent': 0.0}
    assert progress['eta'] is None


def _state_with_queue(tmp_path, statuses):
    store = Store(tmp_path)
    urls = [f'https://wangda.chinamobile.com/#/study/course/detail/subject-course/c{i}/6/s1'
            for i in range(len(statuses))]
    store.write({'status': 'running', 'run_id': 'b' * 32,
                 'last_event': {'ev': 'tick', 'v': {'cur': 300, 'dur': 900, 'rate': 1.5}},
                 'queue': [{'url': u, 'status': s} for u, s in zip(urls, statuses)]})
    return store


def test_eta_uses_the_runs_own_observed_pace(tmp_path, capsys):
    _state_with_queue(tmp_path, ["completed", "completed", "running", "pending", "pending"])
    logs = tmp_path / 'logs'
    logs.mkdir()
    events = []
    for i, seconds in enumerate((600, 300)):
        events.append({'ev': 'course_start', 'course': f'c{i}', 't': 1000 + i * 1000})
        events.append({'ev': 'course_done', 'course': f'c{i}', 't': 1000 + i * 1000 + seconds})
    (logs / f"events-{'b' * 32}.jsonl").write_text('\n'.join(json.dumps(e) for e in events) + '\n')
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    eta = json.loads(capsys.readouterr().out)['progress']['eta']
    # 当前这门剩 (900-300)/1.5 = 400 秒；两门待跑按观测均值 450 秒算 → 400 + 900 = 1300
    assert eta['seconds_per_course'] == 450
    assert eta['sample'] == 2
    assert eta['remaining_courses'] == 2
    assert eta['eta_seconds'] == 1300
    assert eta['basis'] == 'observed_pace'
    assert 'eta_at' in eta


def test_eta_without_history_only_counts_the_current_course(tmp_path, capsys):
    _state_with_queue(tmp_path, ['running', 'pending'])
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    eta = json.loads(capsys.readouterr().out)['progress']['eta']
    assert eta['eta_seconds'] == 400
    assert eta['basis'] == 'current_course_only'


def test_eta_is_absent_for_an_idle_queue(tmp_path, capsys):
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['progress'].get('eta') is None
