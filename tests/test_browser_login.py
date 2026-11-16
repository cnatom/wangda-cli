"""浏览器登录：登录窗口不能带调试端口，CLI 只在那扇窗关掉之后接管。

平台登录页检测到已连接的 devtools 会把自己跳成 about:blank，所以人工登录必须在
「干净窗口」里完成；CLI 之后附着同一 profile 读 localStorage 的 token 并落地。
"""
import itertools
import json
import os
import stat
from unittest.mock import patch

import pytest

from wangda import adapter, auth, engine
from wangda.adapter import LoginRequired, browser_login
from wangda.browser import Browser
from wangda.config import load_config

SIGNED_IN_HREF = 'https://wangda.chinamobile.com/#/home'
SIGNED_IN_BODY = '我的学习 首页 我的课程 学习档案 ' * 6
LOGIN_HREF = 'https://wangda.chinamobile.com/oauth/#login/abc'
LOGIN_BODY = '短信验证登录 获取验证码'


class FakeProc:
    """poll() 先返回 None（窗口还开着），若干次后返回 0（用户关掉了它）。"""

    def __init__(self, open_polls=2):
        self.calls = 0
        self.open_polls = open_polls
        self.terminated = False

    def poll(self):
        self.calls += 1
        return None if self.calls <= self.open_polls else 0

    def terminate(self):
        self.terminated = True


class FakePage:
    def __init__(self, token, signed_in=True, wall_text=LOGIN_BODY):
        self.token = token
        self._signed_in = signed_in
        self.wall_text = wall_text
        self.closed = False
        self.gotos = []

    def goto(self, url, wait=0):
        self.gotos.append(url)

    def js(self, source):
        if 'location.href' in source:
            return SIGNED_IN_HREF if self._signed_in else LOGIN_HREF
        if 'body' in source:
            return SIGNED_IN_BODY if self._signed_in else self.wall_text
        if "localStorage.getItem('token')" in source:
            return json.dumps(self.token) if self.token else None
        return ''

    def close(self):
        self.closed = True


class FakeBrowser:
    page_obj = None
    attached_headed = None
    proc = None
    signatures = [b'']

    def token_signature(self):
        signatures = FakeBrowser.signatures
        return signatures.pop(0) if len(signatures) > 1 else signatures[0]

    def __init__(self, config):
        pass

    def launch_plain(self, url, headed=True):
        FakeBrowser.proc = FakeBrowser.proc or FakeProc()
        return FakeBrowser.proc

    def open(self, headed=False):
        FakeBrowser.attached_headed = headed

    def page(self):
        return FakeBrowser.page_obj

    def close(self):
        pass


def login(tmp_path, page, timeout=5, proc=None, signatures=None):
    FakeBrowser.page_obj = page
    FakeBrowser.attached_headed = None
    FakeBrowser.proc = proc
    FakeBrowser.signatures = signatures or [b'']
    with patch.object(adapter, 'Browser', FakeBrowser), \
            patch.object(adapter.time, 'sleep', lambda seconds: None), \
            patch.object(adapter.time, 'monotonic', side_effect=itertools.count()):
        return browser_login(load_config(data_dir=tmp_path, env={}), timeout=timeout, poll=0)


def test_login_adopts_the_session_after_the_plain_window_closes(tmp_path):
    page = FakePage({'access_token': 'abc123', 'token_type': 'Bearer'})
    session = login(tmp_path, page)
    path = tmp_path / auth.SESSION_FILE
    saved = json.loads(path.read_text())
    assert session['access_token'] == 'abc123'
    assert saved['source'] == 'browser'
    assert saved['expires_in'] == auth.DEFAULT_EXPIRES_IN
    assert auth.is_fresh(saved)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert FakeBrowser.attached_headed is False        # 接管阶段必须无头
    assert page.closed is True


def test_a_stale_token_behind_the_login_wall_is_never_adopted(tmp_path):
    page = FakePage({'access_token': 'stale'}, signed_in=False)
    with pytest.raises(LoginRequired):
        login(tmp_path, page)
    assert not (tmp_path / auth.SESSION_FILE).exists()


def test_blank_page_with_a_readable_token_is_not_a_session(tmp_path):
    """about:blank 继承 opener 的源：token 读得到，但页面没有任何内容。"""
    page = FakePage({'access_token': 'stale'}, signed_in=False, wall_text='')
    with pytest.raises(LoginRequired):
        login(tmp_path, page)
    assert not (tmp_path / auth.SESSION_FILE).exists()


def test_window_left_open_times_out_and_is_terminated(tmp_path):
    proc = FakeProc(open_polls=10**9)
    with pytest.raises(LoginRequired):
        login(tmp_path, FakePage({'access_token': 'x'}), timeout=5, proc=proc)
    assert proc.terminated is True
    assert not (tmp_path / auth.SESSION_FILE).exists()


def test_token_record_written_to_local_storage_ends_the_wait_even_if_chrome_stays_alive(tmp_path):
    """Chrome 关窗后进程仍在：网大写入了新的 token 记录同样说明登录已完成。"""
    proc = FakeProc(open_polls=10**9)
    page = FakePage({'access_token': 'abc123'})
    session = login(tmp_path, page, proc=proc, signatures=[b'', b'token-123'])
    assert session['access_token'] == 'abc123'
    assert proc.terminated is True                      # 接管前先收掉残留进程
    assert FakeBrowser.attached_headed is False


def test_no_token_after_closing_is_rejected(tmp_path):
    with pytest.raises(LoginRequired):
        login(tmp_path, FakePage(None))


def test_signed_in_rejects_a_page_that_is_not_on_the_platform_host():
    class Blank:
        def js(self, source):
            if 'location.href' in source:
                return 'about:blank'
            return '我的学习 ' * 40

    assert engine.signed_in(Blank()) is False


def test_read_token_js_matches_the_web_app_storage():
    assert "localStorage.getItem('token')" in engine.READ_TOKEN
    assert 'access_token' in engine.READ_TOKEN


def leveldb_path(tmp_path):
    """Create the Local Storage leveldb the dedicated profile would hold."""
    directory = tmp_path / 'profile' / 'Default' / 'Local Storage' / 'leveldb'
    directory.mkdir(parents=True)
    return directory


def test_token_signature_ignores_unrelated_local_storage_writes(tmp_path):
    """页面一加载就会写 localStorage；这些记录不是 token，不能当成登录完成。"""
    leveldb = leveldb_path(tmp_path)
    record = leveldb / '000007.log'
    record.write_bytes(b'#METAhttps://wangda.chinamobile.comisFirstLoginVirsualtrue')
    browser = Browser(load_config(data_dir=tmp_path, profile=tmp_path / 'profile', env={}))
    assert browser.token_signature() == b''
    record.write_bytes(b'#METAhttps://wangda.chinamobile.compopupTurn{"show":false}')
    assert browser.token_signature() == b''            # 噪声写入不改变签名
    assert browser.token_signature() == b''


def test_token_signature_tracks_a_written_token_record(tmp_path):
    leveldb = leveldb_path(tmp_path)
    record = leveldb / '000007.log'
    browser = Browser(load_config(data_dir=tmp_path, profile=tmp_path / 'profile', env={}))
    before = browser.token_signature()
    record.write_bytes(b'\x00\x01tokene\x01{"access_token": "abc", "token_type": "Bearer"}')
    after = browser.token_signature()
    assert len(after) == 32
    assert after != before
    assert browser.token_signature() == after          # 同一条记录保持稳定


def test_a_stale_token_does_not_end_the_wait_before_the_window_closes(tmp_path):
    """profile 里原本就有过期 token：页面噪声写入不能提前收掉登录窗口。"""
    proc = FakeProc(open_polls=3)
    page = FakePage({'access_token': 'old-token'})
    session = login(tmp_path, page, proc=proc, signatures=[b'stale', b'stale', b'stale'])
    assert session['access_token'] == 'old-token'
    assert proc.terminated is False                    # 窗口是自己关掉的，不是被杀掉的
