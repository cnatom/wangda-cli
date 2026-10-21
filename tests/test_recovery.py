from types import SimpleNamespace
from unittest.mock import Mock, patch
from wangda import engine
from wangda.config import load_config
from wangda.runner import Runner
from wangda.state import Store


def test_reattach_keeps_external_page_reference_usable():
    old = SimpleNamespace(ws=Mock(), i=2, close=Mock())
    new = SimpleNamespace(ws=Mock(), i=0, call=Mock())
    tabs = [{'type': 'page', 'url': 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/demo/6/topic',
             'webSocketDebuggerUrl': 'ws://127.0.0.1:1234/test'}]
    with patch.object(engine, 'http_json', return_value=tabs), patch.object(engine, 'Page', return_value=new):
        result = engine.reattach(old, want='/subject-course/demo/')
    assert result is old
    assert old.ws is new.ws


def test_terminal_state_is_published_only_after_cleanup(tmp_path):
    store = Store(tmp_path)
    store.write({'status': 'running', 'queue': []})
    observed = []
    class Browser:
        def close(self):
            observed.append(store.read()['status'])
    runner = Runner(load_config(data_dir=tmp_path, env={}), browser=Browser())
    runner.state = {'status': 'running', 'queue': []}
    runner.finish('stopped')
    assert observed == ['running']
    assert store.read()['status'] == 'stopped'


def test_orphan_recovery_checks_creation_time_and_exact_worker_arguments(tmp_path):
    config = load_config(data_dir=tmp_path, env={})
    browser = Mock()
    runner = Runner(config, browser=browser)
    process = Mock()
    process.create_time.return_value = 100.0
    process.cmdline.return_value = ['python', '-m', 'wangda.worker', str(tmp_path / 'run-config.json'), 'url']
    with patch('wangda.runner.psutil.Process', return_value=process):
        runner.cleanup_orphan({'status': 'running', 'worker': {'pid': 123, 'created': 99.0}})
        process.terminate.assert_not_called()
        runner.cleanup_orphan({'status': 'running', 'worker': {'pid': 123, 'created': 100.0}})
        process.terminate.assert_called_once()


def test_orphan_recovery_never_signals_a_different_command(tmp_path):
    runner = Runner(load_config(data_dir=tmp_path, env={}), browser=Mock())
    process = Mock()
    process.create_time.return_value = 100.0
    process.cmdline.return_value = ['python', '-m', 'another_application']
    with patch('wangda.runner.psutil.Process', return_value=process):
        runner.cleanup_orphan({'status': 'running', 'worker': {'pid': 123, 'created': 100.0}})
    process.terminate.assert_not_called()
