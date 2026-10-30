"""课程总时长：预取一次记住，之后 ETA 直接用确切值。"""
import json

from wangda import durations
from wangda.cli import main
from wangda.state import Store

COURSE = 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/{}/6/s1'


def test_cache_roundtrip_and_ignores_bad_values(tmp_path):
    assert durations.load(tmp_path) == {}
    durations.remember(tmp_path, 'c1', 1560)
    durations.remember(tmp_path, 'c2', 0)          # 无效值不入库
    data = json.loads((tmp_path / durations.FILE).read_text())
    assert list(data) == ['c1']
    assert data['c1']['seconds'] == 1560
    assert durations.seconds_for(tmp_path, 'c1') == 1560
    assert durations.seconds_for(tmp_path, 'c2') is None


def test_eta_uses_recorded_durations_instead_of_the_pace(tmp_path, capsys):
    store = Store(tmp_path)
    store.write({'status': 'running', 'run_id': 'c' * 32,
                 'last_event': {'ev': 'tick', 'v': {'cur': 300, 'dur': 900, 'rate': 1.5}},
                 'queue': [{'url': COURSE.format('c1'), 'status': 'completed'},
                           {'url': COURSE.format('c2'), 'status': 'running'},
                           {'url': COURSE.format('c3'), 'status': 'pending'},
                           {'url': COURSE.format('c4'), 'status': 'pending'}]})
    durations.remember(tmp_path, 'c3', 600)
    durations.remember(tmp_path, 'c4', 900)
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / f"events-{'c' * 32}.jsonl").write_text(json.dumps(
        {'ev': 'course_start', 'course': 'c1', 't': 100}) + '\n' + json.dumps(
        {'ev': 'course_done', 'course': 'c1', 't': 700}) + '\n')
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    eta = json.loads(capsys.readouterr().out)['progress']['eta']
    # 当前剩 (900-300)/1.5 = 400；两门确切时长 (600+900)/1.5 = 1000
    assert eta['eta_seconds'] == 1400
    assert eta['basis'] == 'measured_durations'
    assert eta['known_courses'] == 2 and eta['unknown_courses'] == 0
    assert eta['known_seconds_at_rate'] == 1000


def test_unknown_courses_fall_back_to_the_observed_pace(tmp_path, capsys):
    store = Store(tmp_path)
    store.write({'status': 'running', 'run_id': 'd' * 32,
                 'config': {'rate': 1.5},
                 'last_event': {'ev': 'tick', 'v': {'cur': 0, 'dur': 0, 'rate': 1.5}},
                 'queue': [{'url': COURSE.format('c3'), 'status': 'pending'},
                           {'url': COURSE.format('c4'), 'status': 'pending'}]})
    durations.remember(tmp_path, 'c3', 300)
    logs = tmp_path / 'logs'
    logs.mkdir()
    (logs / f"events-{'d' * 32}.jsonl").write_text(
        json.dumps({'ev': 'course_start', 'course': 'x', 't': 0}) + '\n'
        + json.dumps({'ev': 'course_done', 'course': 'x', 't': 900}) + '\n')
    assert main(['status', '--data-dir', str(tmp_path), '--json']) == 0
    eta = json.loads(capsys.readouterr().out)['progress']['eta']
    assert eta['basis'] == 'measured_plus_pace'
    assert eta['known_courses'] == 1 and eta['unknown_courses'] == 1
    assert eta['eta_seconds'] == 200 + 900          # 300/1.5 + 实测 900
