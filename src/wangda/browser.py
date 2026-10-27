"""Dedicated Chromium processes and CDP; never attach to a user's normal profile."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import psutil
import websocket

ANTI_FREEZE = [
    '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-features=CalculateNativeWinOcclusion,TabFreeze,ProactiveTabFreezeAndDiscard',
]


def discover_browser(explicit=None):
    if explicit:
        found = shutil.which(explicit) or (str(Path(explicit).expanduser()) if Path(explicit).expanduser().is_file() else None)
        if not found:
            raise FileNotFoundError('Configured browser executable was not found')
        return found
    candidates = [shutil.which(name) for name in ('google-chrome', 'chromium', 'chromium-browser', 'chrome', 'msedge')]
    if sys.platform == 'darwin':
        candidates += ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                       '/Applications/Chromium.app/Contents/MacOS/Chromium',
                       str(Path.home() / 'Applications/Google Chrome.app/Contents/MacOS/Google Chrome')]
    elif sys.platform == 'win32':
        for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            if prefix := os.environ.get(key):
                candidates += [str(Path(prefix) / 'Google/Chrome/Application/chrome.exe'),
                               str(Path(prefix) / 'Microsoft/Edge/Application/msedge.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError('Install Google Chrome/Chromium or set WANDA_BROWSER')


class Page:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
        self.i = 0

    def call(self, method, **params):
        self.i += 1
        expected = self.i
        self.ws.send(json.dumps({'id': expected, 'method': method, 'params': params}))
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            self.ws.settimeout(max(0.1, deadline - time.monotonic()))
            message = json.loads(self.ws.recv())
            if message.get('method') == 'Page.javascriptDialogOpening':
                self.ws.send(json.dumps({'id': -expected, 'method': 'Page.handleJavaScriptDialog',
                                         'params': {'accept': True}}))
            if message.get('id') == expected:
                if 'error' in message:
                    raise RuntimeError(f'CDP method failed: {method}')
                return message.get('result', {})
        raise TimeoutError(f'CDP timeout: {method}')

    def js(self, expression, timeout=30):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True,
                           awaitPromise=True, timeout=timeout * 1000)
        if result.get('exceptionDetails'):
            # The remote exception can contain authentication data; do not echo it.
            raise RuntimeError('Page JavaScript evaluation failed')
        return result.get('result', {}).get('value')

    def goto(self, url, wait=6):
        host = 'https://wangda.chinamobile.com'
        if url.startswith(host) and not (self.js('location.href') or '').startswith(host):
            self.call('Page.navigate', url=host + '/')
            time.sleep(2)
        try:
            self.js('location.href = ' + json.dumps(url))
        except Exception:
            self.call('Page.navigate', url=url)
        time.sleep(min(2, wait))
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                # Platform adapter separately checks visible course/list/login states.
                if self.js("!!document.body && document.body.innerText.trim().length > 0"):
                    break
            except Exception:
                pass
            time.sleep(0.5)

    def mouse_move(self, x=500, y=350):
        self.call('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y, buttons=0)

    def close(self):
        self.ws.close()


class Browser:
    def __init__(self, config):
        self.config = config

    @property
    def port(self):
        if self.config.port:
            return self.config.port
        try:
            return int((self.config.profile / 'DevToolsActivePort').read_text().splitlines()[0])
        except (FileNotFoundError, IndexError, ValueError):
            raise RuntimeError('Dedicated browser CDP port is not available') from None

    def owned(self, processes=None):
        processes = psutil.process_iter(['pid', 'cmdline']) if processes is None else processes
        flag = f'--user-data-dir={self.config.profile}'
        result = []
        for proc in processes:
            try:
                args = proc.info.get('cmdline') or []
                if flag in args and not any(a.startswith('--type=') for a in args):
                    result.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return result

    def http_json(self, path, method='GET'):
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', method=method)
        # Never send local CDP through a system HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    def close(self):
        processes = self.owned()
        for proc in processes:
            try:
                proc.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(processes, timeout=5)
        for proc in alive:
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=3)

    def open(self, headed=False):
        owned = self.owned()
        if owned:
            args = owned[0].info['cmdline']
            if ('--headless=new' in args) == (not headed):
                self.http_json('/json/version')
                return
            self.close()
        executable = discover_browser(self.config.browser)
        self.config.profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.config.port:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', self.config.port))
        else:
            (self.config.profile / 'DevToolsActivePort').unlink(missing_ok=True)
        args = [executable, f'--user-data-dir={self.config.profile}',
                f'--remote-debugging-port={self.config.port}', '--remote-debugging-address=127.0.0.1',
                '--no-first-run', '--no-default-browser-check', '--window-size=1280,900',
                '--autoplay-policy=no-user-gesture-required', '--mute-audio', *ANTI_FREEZE]
        if not headed:
            args += ['--headless=new']
        args += ['about:blank']
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            try:
                self.http_json('/json/version')
                if self.owned():
                    return
            except Exception:
                pass
            time.sleep(0.25)
        self.close()
        raise RuntimeError('Dedicated browser did not start within 35 seconds')

    def page(self):
        tabs = [t for t in self.http_json('/json/list') if t.get('type') == 'page']
        target = tabs[0] if tabs else self.http_json('/json/new?about:blank', method='PUT')
        page = Page(target['webSocketDebuggerUrl'])
        page.call('Page.enable')
        page.call('Runtime.enable')
        ua = self.http_json('/json/version').get('User-Agent', '').replace('HeadlessChrome/', 'Chrome/')
        if ua:
            page.call('Network.setUserAgentOverride', userAgent=ua)
        return page
