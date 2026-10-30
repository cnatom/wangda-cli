"""Offline tests for the browser-free login protocol. No network, no account."""
import base64
import json
import os
import stat

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wangda import auth


def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, pem


def decrypt(private, fields):
    key = private.decrypt(base64.b64decode(fields['secureKey']), asym_padding.PKCS1v15())
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    body = decryptor.update(base64.b64decode(fields['secureData'])) + decryptor.finalize()
    pad = body[-1]
    return key.decode(), json.loads(body[:-pad])


class FakeTransport(auth.Transport):
    def __init__(self, pem, sms=None, members=None, auth_body=None):
        super().__init__('https://wangda.test')
        self.pem = pem
        self.calls = []
        self.sms = {'phoneNumber': '13800001234'} if sms is None else sms
        self.members = members if members is not None else {
            'members': [{'id': 'member-1'}], 'check_token': 'check-1', 'pass': 0}
        self.auth_body = auth_body or {'access_token': 'tok-1', 'token_type': 'Bearer',
                                       'expires_in': 3600, 'redirect_uri': 'https://wangda.test'}

    def get_json(self, path):
        self.calls.append(('GET', path, None))
        if path == auth.SETTING:
            return {'rsaPublicKey': self.pem}
        raise AssertionError(path)

    def get_text(self, path):
        self.calls.append(('GET', path, None))
        assert path.startswith(auth.SIGN)
        return json.dumps({'sign': 'sign-1'})

    def post_form(self, path, fields):
        self.calls.append(('POST', path, fields))
        return {auth.SMS: self.sms, auth.MEMBERS: self.members, auth.AUTH: self.auth_body}[path]


def test_hybrid_wrap_matches_the_browser_envelope():
    private, pem = keypair()
    key, payload = decrypt(private, auth.hybrid_wrap(pem, {'username': 'u', 'key': 'no-date'}, key='K' * 16))
    assert key == 'K' * 16
    assert payload == {'username': 'u', 'key': 'no-date'}


def test_hybrid_wrap_uses_a_new_random_key_each_call():
    _, pem = keypair()
    first = auth.hybrid_wrap(pem, {'a': 1})
    second = auth.hybrid_wrap(pem, {'a': 1})
    assert first['secureData'] != second['secureData']


def test_authenticate_wraps_sms_and_members_but_not_auth():
    private, pem = keypair()
    transport = FakeTransport(pem)
    session = auth.authenticate(transport, '13800000000', lambda phone: '123456')

    paths = [(method, path.split('?')[0]) for method, path, _ in transport.calls]
    assert paths == [('GET', auth.SETTING), ('GET', '/api/v1/system/sign/generate'),
                     ('POST', auth.SMS), ('POST', auth.MEMBERS), ('POST', auth.AUTH)]

    sms = decrypt(private, transport.calls[2][2])[1]
    assert sms == {'key': 'no-date', 'username': '13800000000', 'sign': 'sign-1'}
    members = decrypt(private, transport.calls[3][2])[1]
    assert members == {'key': 'no-date', 'username': '13800000000',
                       'password': '123456', 'loginType': '1'}
    assert transport.calls[4][2] == {'key': 'no-date', 'userid': 'member-1',
                                     'check_token': 'check-1', 'password': '123456'}

    assert session['access_token'] == 'tok-1'
    assert auth.authorization(session) == 'Bearer__tok-1'
    assert auth.is_fresh(session)
    assert '123456' not in json.dumps(session)


def test_authenticate_reports_platform_error_code():
    _, pem = keypair()
    transport = FakeTransport(pem, sms={'errorCode': 90105, 'message': 'account not found'})
    with pytest.raises(auth.AuthError, match='90105'):
        auth.authenticate(transport, '13800000000', lambda phone: '123456')


def test_authenticate_refuses_department_choice():
    _, pem = keypair()
    transport = FakeTransport(pem, members={'members': [{'id': 'a'}, {'id': 'b'}],
                                            'check_token': 'c', 'pass': 1})
    with pytest.raises(auth.AuthError, match='department'):
        auth.authenticate(transport, '13800000000', lambda phone: '123456')


def test_probe_never_sends_an_sms():
    _, pem = keypair()
    transport = FakeTransport(pem)
    result = auth.probe(transport)
    assert result['sign_present'] is True
    assert [call[0] for call in transport.calls] == ['GET', 'GET']
    assert '13800000000' not in json.dumps(result)


def test_session_file_is_private_and_roundtrips(tmp_path):
    path = auth.write_private_json(tmp_path / auth.SESSION_FILE,
                                   {'access_token': 'tok', 'token_type': 'Bearer',
                                    'expires_in': 60, 'obtained_at': 0})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert auth.read_session(path)['access_token'] == 'tok'
    assert not auth.is_fresh(auth.read_session(path))


def test_read_session_refuses_world_readable_file(tmp_path):
    path = tmp_path / auth.SESSION_FILE
    path.write_text(json.dumps({'access_token': 'tok'}))
    os.chmod(path, 0o644)
    with pytest.raises(auth.AuthError, match='readable by others'):
        auth.read_session(path)


def test_mask_phone_hides_the_middle():
    assert auth.mask_phone('13800001234') == '138****1234'
    assert auth.mask_phone('') == '***'


def test_write_private_json_survives_hosts_without_posix_modes(tmp_path, monkeypatch):
    """Windows has no os.fchmod; the write must still land and round-trip."""
    monkeypatch.setattr(auth, '_enforce_posix_private_mode', lambda: False)

    def no_fchmod(fd, mode):
        raise PermissionError('os.fchmod is not available on this host')

    monkeypatch.setattr(auth.os, 'fchmod', no_fchmod, raising=False)
    path = auth.write_private_json(tmp_path / auth.SESSION_FILE,
                                   {'access_token': 'tok', 'token_type': 'Bearer',
                                    'expires_in': 60, 'obtained_at': 0})
    assert auth.read_session(path)['access_token'] == 'tok'
    assert not list(tmp_path.glob('*.tmp'))


def test_read_session_skips_posix_mode_check_without_posix_modes(tmp_path, monkeypatch):
    """On Windows st_mode always carries group/other bits, so the 0600 test is noise."""
    path = tmp_path / auth.SESSION_FILE
    path.write_text(json.dumps({'access_token': 'tok'}))
    os.chmod(path, 0o644)
    monkeypatch.setattr(auth, '_enforce_posix_private_mode', lambda: False)
    assert auth.read_session(path)['access_token'] == 'tok'

