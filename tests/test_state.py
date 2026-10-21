import json
import pytest
from filelock import Timeout
from wangda.config import load_config
from wangda.state import Store, exclusive, scrub


def test_snapshot_write_is_atomic_and_read_has_no_browser_side_effects(tmp_path):
    store = Store(tmp_path)
    assert store.read()['status'] == 'idle'
    store.write({'status': 'paused', 'run_id': 'one', 'queue': []})
    result = store.read()
    assert result['schema_version'] == 1
    assert result['status'] == 'paused'
    assert not list(tmp_path.glob('*.tmp'))


def test_two_data_dirs_cannot_share_a_live_profile(tmp_path):
    profile = tmp_path / 'shared profile'
    one = load_config(data_dir=tmp_path / 'one', profile=profile, env={})
    two = load_config(data_dir=tmp_path / 'two', profile=profile, env={})
    with exclusive(one):
        with pytest.raises(Timeout):
            with exclusive(two):
                pass


def test_tokens_are_redacted_recursively_and_bearer_not_persisted(tmp_path):
    store = Store(tmp_path)
    store.write({'status': 'failed', 'access_token': 'private',
                 'detail': 'Authorization: Bearer abcXYZ',
                 'url': 'https://example.test/?token=secret&other=value',
                 'nested': {'cookie': 'private'}})
    text = (tmp_path / 'state.json').read_text()
    assert 'private' not in text and 'abcXYZ' not in text and 'secret' not in text
    assert 'other=value' in text
    assert scrub({'phone': '13800000000'})['phone'] == '[redacted]'


def test_control_is_bound_to_a_specific_run(tmp_path):
    store = Store(tmp_path)
    store.control('pause', 'one')
    assert store.command('two') is None
    assert store.command('one') == 'pause'
    assert json.loads((tmp_path / 'control.json').read_text())['run_id'] == 'one'
