"""Atomic local snapshots, run-scoped commands and cross-process locks."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time

from filelock import FileLock

SENSITIVE = re.compile(r'(token|authorization|cookie|password|secret|phone|mobile|sms)', re.I)


def scrub(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if SENSITIVE.search(str(k)) else scrub(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'(?i)(bearer\s+)[^\s"\x27,}]+', r'\1[redacted]', value)
        value = re.sub(r'(?i)(authorization\s*[:=]\s*)[^\n,}]+', r'\1[redacted]', value)
        value = re.sub(r'(?i)([?&](?:access_token|refresh_token|token|code|secret|password)=)[^&#\s]*', r'\1[redacted]', value)
        return re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[redacted]', value)
    return value


def retry_sharing_violation(operation):
    """Windows readers/AV can briefly deny access or replacement; never retry forever."""
    for attempt in range(20):
        try:
            return operation()
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(min(0.05, 0.002 * 2 ** attempt))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(scrub(value), handle, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        retry_sharing_violation(lambda: os.replace(name, path))
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path, default=None):
    try:
        return json.loads(retry_sharing_violation(lambda: Path(path).read_text(encoding='utf-8')))
    except FileNotFoundError:
        return default


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)

    def read(self):
        return read_json(self.directory / 'state.json', {'schema_version': 1, 'status': 'idle', 'queue': []})

    def write(self, value):
        atomic_json(self.directory / 'state.json', {**value, 'schema_version': 1, 'updated_at': timestamp()})

    def control(self, action, run_id):
        if action not in ('pause', 'stop'):
            raise ValueError('Unknown control action')
        atomic_json(self.directory / 'control.json', {'run_id': run_id, 'action': action})

    def command(self, run_id):
        value = read_json(self.directory / 'control.json', {})
        return value.get('action') if value.get('run_id') == run_id else None


@contextmanager
def exclusive(config):
    config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.profile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Canonical profile path is the lock identity, even across distinct data dirs.
    with FileLock(str(config.data_dir / 'runner.lock'), timeout=0):
        with FileLock(str(config.profile) + '.wanda.lock', timeout=0):
            yield
