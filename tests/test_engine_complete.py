"""课程页完成判据：计数器优先，缺失时退回逐节可见状态。"""
from wangda.engine import all_sections_done, page_full_kind


def test_counter_full_wins_even_when_sections_look_done():
    assert page_full_kind('完成 6 节 / 共 6 节', ['视频 已完成'] * 6) == 'counter'


def test_counter_short_of_total_is_not_full():
    assert page_full_kind('完成 5 节 / 共 6 节', ['视频 已完成'] * 6) is None


def test_missing_counter_falls_back_to_section_states():
    assert page_full_kind('', ['视频 已完成', '视频 已完成']) == 'sections'


def test_missing_counter_with_an_unfinished_section_is_not_full():
    assert page_full_kind('', ['视频 已完成', '视频 学习中']) is None


def test_empty_section_list_is_never_full():
    assert page_full_kind('', []) is None
    assert page_full_kind(None, ['', '  ']) is None
    assert all_sections_done(['']) is False
