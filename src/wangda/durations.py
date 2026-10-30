"""Course durations read from the platform's own 「课程总时长」.

Course lengths do not change for a given course id, so the cache never expires; the only
way a value is refreshed is an explicit `--refresh-durations`. Values are raw seconds;
the playback rate is applied wherever they are used.
"""
import json
import time
from pathlib import Path

from .state import atomic_json

FILE = 'durations.json'


def path_of(data_dir):
    return Path(data_dir) / FILE


def load(data_dir):
    path = path_of(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def remember(data_dir, course_id, seconds, source='page'):
    if not course_id or not isinstance(seconds, (int, float)) or seconds <= 0:
        return load(data_dir)
    data = load(data_dir)
    data[course_id] = {'seconds': int(seconds), 'source': source,
                       'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    atomic_json(path_of(data_dir), data)
    return data


def seconds_for(data_dir, course_id, cache=None):
    data = cache if cache is not None else load(data_dir)
    entry = data.get(course_id) or {}
    value = entry.get('seconds')
    return value if isinstance(value, (int, float)) and value > 0 else None
