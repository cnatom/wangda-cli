"""Real subprocess supervision tests, entirely offline and without real accounts."""
import os
from pathlib import Path
import time
from unittest.mock import patch

from wangda.cli import start_background, control
from wangda.config import load_config
from wangda.state import Store

URL = 'https://wangda.chinamobile.com/#/study/subject/detail/demo-offline/1'


def test_detached_start_acknowledgement_stop_and_resume(tmp_path):
    # A separate, synthetic worker implements the event protocol, not platform completion.
    site = tmp_path / 'synthetic-worker'
    (site / 'wangda').mkdir(parents=True)
    real_package = Path(__file__).resolve().parents[1] / 'src' / 'wangda'
    (site / 'wangda' / '__init__.py').write_text('__path__.append(' + repr(str(real_package)) + ')')
    (site / 'wangda' / 'worker.py').write_text(
        'import json,time\n'
        'while True:\n'
        ' print(json.dumps({"ev":"tick","v":{"cur":1,"dur":60}}),flush=True)\n'
        ' time.sleep(.05)\n')
    cfg = load_config(data_dir=tmp_path / 'run', poll_seconds=.02, env={})
    with patch.dict(os.environ, {'PYTHONPATH': str(site)}):
        state = start_background(cfg, [URL], False)
        try:
            assert state['status'] == 'running'
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state = Store(cfg.data_dir).read()
                if state.get('last_event', {}).get('ev') == 'tick':
                    break
                time.sleep(.02)
            assert state['last_event']['ev'] == 'tick'
            paused = control(cfg, 'pause', 10)
            assert paused['status'] == 'paused'
            assert paused['queue'][0]['status'] == 'paused'
            state2 = start_background(cfg, None, True)
            assert state2['run_id'] != state['run_id']
            stopped = control(cfg, 'stop', 10)
            assert stopped['status'] == 'stopped'
        finally:
            control(cfg, 'stop', 10)


def test_background_failure_is_saved_and_cli_errors_do_not_leak_raw_output(tmp_path):
    cfg = load_config(data_dir=tmp_path, browser=str(tmp_path / 'missing-browser'), retries=0,
                      poll_seconds=.02, env={})
    state = start_background(cfg, [URL], False)
    deadline = time.monotonic() + 10
    while state['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.05)
        state = Store(tmp_path).read()
    assert state['status'] == 'failed'
    assert state['last_event']['reason'] == 'FileNotFoundError'
