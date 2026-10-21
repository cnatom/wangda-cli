from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from wangda.config import load_config
from wangda.browser import Browser, discover_browser


def test_explicit_browser_discovery_requires_existing_executable(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_browser(str(tmp_path / 'missing'))


def test_browser_ownership_uses_exact_profile_argument_and_main_process(tmp_path):
    config = load_config(data_dir=tmp_path, env={})
    browser = Browser(config)
    def proc(pid, args):
        return SimpleNamespace(info={'pid': pid, 'cmdline': args})
    processes = [proc(11, ['chrome', f'--user-data-dir={config.profile}']),
                 proc(12, ['chrome', f'--user-data-dir={config.profile}-other']),
                 proc(13, ['chrome', f'--user-data-dir={config.profile}', '--type=renderer'])]
    assert [p.info['pid'] for p in browser.owned(processes)] == [11]


def test_browser_close_never_signals_unowned_process(tmp_path):
    browser = Browser(load_config(data_dir=tmp_path, env={}))
    mine, other = Mock(), Mock()
    browser.owned = lambda: [mine]
    from unittest.mock import patch
    with patch('wangda.browser.psutil.wait_procs', return_value=([], [])):
        browser.close()
    mine.terminate.assert_called_once()
    other.terminate.assert_not_called()


def test_dynamic_port_is_read_from_dedicated_profile(tmp_path):
    browser = Browser(load_config(data_dir=tmp_path, env={}))
    browser.config.profile.mkdir()
    (browser.config.profile / 'DevToolsActivePort').write_text('12345\n/devtools/browser/test\n')
    assert browser.port == 12345
