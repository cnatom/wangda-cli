from unittest.mock import Mock, patch
import pytest
from wangda import engine
from wangda.adapter import validate_url, play, LoginRequired, Unconfirmed, UnsupportedItem
from wangda.config import load_config

SUBJECT = 'https://wangda.chinamobile.com/#/study/subject/detail/demo-topic/1'
COURSE = 'https://wangda.chinamobile.com/#/study/course/detail/subject-course/demo-course/6/demo-topic'


def test_url_validation_preserves_valid_input_and_rejects_other_origins():
    assert validate_url(SUBJECT) == SUBJECT
    assert validate_url(COURSE) == COURSE
    for url in ('https://example.com/#/study/subject/detail/a',
                'https://wangda.chinamobile.com.evil.test/#/study/subject/detail/a',
                'http://wangda.chinamobile.com/#/study/subject/detail/a',
                SUBJECT + '?token=private', 'https://wangda.chinamobile.com/',
                'https://user:pass@wangda.chinamobile.com/#/study/subject/detail/a',  # pragma: allowlist secret (synthetic rejection fixture)
                SUBJECT + '/../../x', SUBJECT + '\n'):
        with pytest.raises(ValueError):
            validate_url(url)


def setup_browser():
    browser = Mock()
    page = browser.page.return_value
    page.js.return_value = 'ready'
    return browser, page


def test_failed_course_is_not_reported_success(tmp_path):
    browser, page = setup_browser()
    with patch.object(engine, 'run_course', return_value=False), patch.object(engine, 'is_login_wall', return_value=False):
        with pytest.raises(Unconfirmed):
            play(browser, load_config(data_dir=tmp_path, env={}), COURSE)
    browser.close.assert_called_once()
    page.close.assert_called_once()


def test_empty_subject_is_not_completed(tmp_path):
    browser, _ = setup_browser()
    with patch('wangda.adapter.read_subject', side_effect=Unconfirmed('No visible curriculum')):
        with pytest.raises(Unconfirmed):
            play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)
    browser.close.assert_called_once()


def test_login_is_a_terminal_wait_not_a_retry(tmp_path):
    browser, _ = setup_browser()
    with patch('wangda.adapter.read_subject', side_effect=LoginRequired()):
        with pytest.raises(LoginRequired):
            play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)


def test_unknown_item_type_is_not_clicked(tmp_path):
    browser, _ = setup_browser()
    data = {'progress': '完成 0 项 / 共 1 项', 'items': [{'id': 'a', 'type': '99', 'st': '未开始'}]}
    with patch('wangda.adapter.read_subject', return_value=data), patch.object(engine, 'click_item') as click:
        with pytest.raises(UnsupportedItem):
            play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)
        click.assert_not_called()


def test_topic_requires_final_platform_confirmation(tmp_path):
    browser, _ = setup_browser()
    pending = {'progress': '0/1', 'items': [{'id': 'a', 'type': '10', 'st': '未开始'}]}
    completed = {'progress': '1/1', 'items': [{'id': 'a', 'type': '10', 'st': '已完成'}]}
    with patch('wangda.adapter.read_subject', side_effect=[pending, completed]), \
         patch.object(engine, 'run_course', return_value=True):
        assert play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)['verified'] is True


@pytest.mark.parametrize('target_present', [True, False])
def test_direct_course_does_not_complete_when_only_a_different_card_is_completed(tmp_path, target_present):
    browser, _ = setup_browser()
    items = [{'id': 'different-course', 'type': '10', 'st': '已完成'}]
    if target_present:
        items.append({'id': 'demo-course', 'type': '10', 'st': '未开始'})
    cards = {'progress': '', 'items': items}
    config = load_config(data_dir=tmp_path, confirmation_seconds=0.01, poll_seconds=0.001, env={})
    with patch.object(engine, 'run_course', return_value=True) as playback, \
         patch('wangda.adapter.read_subject', return_value=cards), \
         patch.object(engine, 'log'), patch('wangda.adapter.time.sleep'):
        with pytest.raises(Unconfirmed):
            play(browser, config, COURSE)
    playback.assert_called_once()


def test_delayed_exact_card_confirmation_reloads_without_replaying_course(tmp_path):
    browser, page = setup_browser()
    pending = {'progress': '', 'items': [{'id': 'demo-course', 'type': '10', 'st': '未开始'}]}
    completed = {'progress': '', 'items': [{'id': 'demo-course', 'type': '10', 'st': '已完成'}]}
    with patch.object(engine, 'run_course', return_value=True) as playback, \
         patch('wangda.adapter.read_subject', side_effect=[pending, completed]) as subject_read, \
         patch.object(engine, 'log'), patch('wangda.adapter.time.sleep'):
        result = play(browser, load_config(data_dir=tmp_path, env={}), COURSE)
    assert result['confirmation'] == 'course_and_subject'
    assert result['card_status'] == '已完成'
    assert subject_read.call_count == 2
    page.call.assert_any_call('Page.reload', ignoreCache=True)
    page.js.assert_any_call(engine.STOP_PLAYBACK)
    playback.assert_called_once()
