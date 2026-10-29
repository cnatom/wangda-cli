"""Browser-free login: obtain a Wangda token over HTTP only.

The platform's `/oauth` app protects selected payloads with a hybrid envelope
(`./app/util/hybrid-crypto` in its bundle):

    key        = 16 random characters, per request
    secureKey  = RSA-PKCS1v15(key)                       -> base64
    secureData = AES-128-ECB(PKCS7, json(payload), key)  -> base64

Only models declared `security:"hybrid"` use it. `auth` does not. The RSA public
key is served unauthenticated by `/oauth/api/v1/setting`.

Nothing here fabricates learning records: it authenticates the same way the web
app does, and the browser still plays the course.
"""
import base64
import getpass
import json
import os
import secrets
import stat
import string
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SETTING = '/oauth/api/v1/setting'
SIGN = '/api/v1/system/sign/generate?prefix=oauth-login&_='
SMS = '/oauth/api/v1/dynamic-password-sign'
MEMBERS = '/oauth/api/v1/members-encrypt'
AUTH = '/oauth/api/v1/auth'
# The web app routes to `#login/no-date`; the route segment doubles as the payload `key`.
SIGN_KEY = 'no-date'
KEY_ALPHABET = string.ascii_letters + string.digits
SESSION_FILE = 'session.json'
# 网页端登录只拿到 access_token；平台声明的有效期是 4 小时（observed 14400）。
DEFAULT_EXPIRES_IN = 14400
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36')


class AuthError(Exception):
    """A login step failed; the detail is safe to show."""


def mask_phone(value):
    text = str(value or '')
    return f'{text[:3]}****{text[-4:]}' if len(text) >= 7 else '***'


def random_key():
    return ''.join(secrets.choice(KEY_ALPHABET) for _ in range(16))


def hybrid_wrap(public_key_pem, payload, key=None):
    """Return the form fields the platform expects for a hybrid-protected model."""
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    if not isinstance(public_key, RSAPublicKey):
        raise AuthError('setting key is not an RSA public key')
    key = key or random_key()
    secure_key = base64.b64encode(public_key.encrypt(key.encode(), asym_padding.PKCS1v15())).decode()
    padder = padding.PKCS7(128).padder()
    body = padder.update(json.dumps(payload).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key.encode()), modes.ECB()).encryptor()
    secure_data = base64.b64encode(encryptor.update(body) + encryptor.finalize()).decode()
    return {'secureKey': secure_key, 'secureData': secure_data}


class Transport:
    """Minimal form-encoded HTTP client; one opener so tests stay offline."""

    def __init__(self, host, opener=urlopen, timeout=20):
        self.host = host.rstrip('/')
        self.opener = opener
        self.timeout = timeout

    def _open(self, path, data=None):
        headers = {'User-Agent': USER_AGENT,
                   'Accept': 'application/json, text/javascript, */*; q=0.01',
                   'X-Requested-With': 'XMLHttpRequest'}
        body = None
        if data is not None:
            body = urlencode(data).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
        request = Request(self.host + path, data=body, headers=headers)
        with self.opener(request, timeout=self.timeout) as response:
            return response.read().decode('utf-8', 'replace')

    def get_text(self, path):
        return self._open(path)

    def get_json(self, path):
        return json.loads(self._open(path))

    def post_form(self, path, fields):
        return json.loads(self._open(path, fields))


def _error_code(payload):
    for key in ('errorCode', 'error'):
        value = payload.get(key)
        if isinstance(value, int) and value:
            return value
    return None


def _require(payload, step):
    code = _error_code(payload)
    if code is not None:
        raise AuthError(f'{step} failed: errorCode {code} ({payload.get("message") or "no message"})')
    return payload


def public_key(transport):
    return _require(transport.get_json(SETTING), 'setting').get('rsaPublicKey') or ''


def sign(transport):
    # The endpoint answers with a JSON document served as text/javascript.
    body = transport.get_text(SIGN + str(int(time.time() * 1000)))
    value = json.loads(body).get('sign')
    if not value:
        raise AuthError('sign/generate returned no sign')
    return value


def probe(transport):
    """Read-only checks: public key and sign endpoint. Never sends an SMS."""
    pem = public_key(transport)
    if not pem.startswith('-----BEGIN PUBLIC KEY-----'):
        raise AuthError('setting returned no usable rsaPublicKey')
    return {'public_key_sha256': _fingerprint(pem), 'sign_present': bool(sign(transport))}


def _fingerprint(pem):
    import hashlib
    return hashlib.sha256(pem.encode()).hexdigest()[:16]


def authenticate(transport, username, ask_code, key=SIGN_KEY):
    """Run the SMS login. `ask_code(phone)` is injected so tests never prompt."""
    pem = public_key(transport)
    if not pem:
        raise AuthError('setting returned no rsaPublicKey')
    value = sign(transport)

    sms = _require(transport.post_form(SMS, hybrid_wrap(
        pem, {'key': key, 'username': username, 'sign': value})), 'sms')
    code = ask_code(mask_phone(sms.get('phoneNumber') or username))
    if not code:
        raise AuthError('no verification code entered')

    members = _require(transport.post_form(MEMBERS, hybrid_wrap(pem, {
        'key': key, 'username': username, 'password': code, 'loginType': '1'})), 'members-encrypt')
    if members.get('pass') in (1, 3):
        raise AuthError('account belongs to several departments; pick one in the web app first')
    rows = members.get('members') or []
    check_token = members.get('check_token')
    if not rows or not check_token:
        raise AuthError('members-encrypt returned no member or check_token')

    auth = _require(transport.post_form(AUTH, {
        'key': key, 'userid': rows[0].get('id'), 'check_token': check_token, 'password': code}), 'auth')
    if not auth.get('access_token'):
        raise AuthError('auth returned no access_token')
    return {'origin': transport.host, 'username': username,
            'access_token': auth['access_token'], 'token_type': auth.get('token_type') or 'Bearer',
            'expires_in': auth.get('expires_in'), 'redirect_uri': auth.get('redirect_uri'),
            'obtained_at': int(time.time())}


def authorization(session):
    return f"{session['token_type']}__{session['access_token']}"


def is_fresh(session, margin=60):
    expires_in = session.get('expires_in')
    if not isinstance(expires_in, (int, float)) or not session.get('obtained_at'):
        return False
    return time.time() < session['obtained_at'] + expires_in - margin


def write_private_json(path, value):
    """Atomic 0600 write. Deliberately bypasses state.scrub: this file *is* the secret."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return path


def read_session(path):
    path = Path(path)
    if not path.exists():
        return None
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise AuthError('session file is readable by others; chmod 600 it first')
    value = json.loads(path.read_text(encoding='utf-8'))
    return value if value.get('access_token') else None


def prompt_code(phone):
    return getpass.getpass(f'verification code sent to {phone}: ').strip()
