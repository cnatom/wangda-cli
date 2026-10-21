"""Opt-in, offline real Chromium smoke. No account or platform access required."""
import os
import pytest
from wangda.config import load_config
from wangda.browser import Browser


@pytest.mark.skipif(os.environ.get('WANDA_LIVE_BROWSER') != '1', reason='opt-in real browser smoke')
def test_real_headless_browser_is_dedicated_and_cleaned_up(tmp_path):
    config = load_config(data_dir=tmp_path, env={})
    browser = Browser(config)
    try:
        browser.open()
        page = browser.page()
        page.js("document.body.innerHTML='<h1 id=proof>offline-smoke</h1>'")
        assert page.js("document.querySelector('#proof').innerText") == 'offline-smoke'
        assert page.js('document.visibilityState') == 'visible'
        assert browser.owned()
        page.close()
    finally:
        browser.close()
    assert not browser.owned()
    assert config.profile.exists()
