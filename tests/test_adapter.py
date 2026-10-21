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
