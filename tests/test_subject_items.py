"""专题卡片解析：专区式布局没有 .study-status，必须解析成功而不是抛错。"""
import json
import os
import shutil
import subprocess

import pytest

from wangda import engine

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = os.path.join(HERE, 'subject_items_stub.js')


def parse_cards():
    if not shutil.which('node'):
        pytest.skip('node is required for the DOM stub')
    out = subprocess.run(['node', STUB, engine.SUBJECT_ITEMS], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-800:]
    return json.loads(out.stdout)


def test_standard_card_keeps_its_status():
    items = {item['id']: item for item in parse_cards()['items']}
    assert items['std-1']['st'] == '已完成'
    assert items['std-1']['opt'] is False


def test_zone_card_without_status_element_parses_instead_of_raising():
    items = {item['id']: item for item in parse_cards()['items']}
    assert items['zone-1']['st'] == ''
    assert items['zone-1']['btn'] == '开始学习'
    assert items['zone-1']['opt'] is False


def test_optional_tag_still_marks_opt():
    items = {item['id']: item for item in parse_cards()['items']}
    assert items['opt-1']['opt'] is True


def test_progress_text_is_returned():
    assert parse_cards()['progress'] == '完成 1 项 / 共 3 项'
