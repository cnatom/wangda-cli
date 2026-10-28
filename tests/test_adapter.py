import os
import time
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from wangda import auth, engine
from wangda.adapter import (CertificateUnavailable, LoginRequired, Unconfirmed, claim_certificate, download_certificate, download_snapshot, install_session, play,
                            read_certificate_page, validate_url, wait_for_download)
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


def _session(tmp_path, **overrides):
    value = {'origin': engine.HOST, 'username': 'demo', 'access_token': 'tok-1', 'token_type': 'Bearer',
             'expires_in': 3600, 'obtained_at': int(time.time())}
    value.update(overrides)
    return auth.write_private_json(tmp_path / auth.SESSION_FILE, value)


def test_install_session_writes_the_web_app_localstorage_entry(tmp_path):
    _, page = setup_browser()
    _session(tmp_path)
    session = install_session(page, load_config(data_dir=tmp_path, env={}))
    assert session['access_token'] == 'tok-1'
    page.goto.assert_called_once_with(engine.HOST + '/', wait=6)
    expression = page.js.call_args[0][0]
    assert expression.startswith("localStorage.setItem('token', ")
    assert 'tok-1' in expression and 'is_weak_pwd' in expression and 'Bearer' in expression


def test_install_session_skips_a_missing_or_expired_session(tmp_path):
    _, page = setup_browser()
    config = load_config(data_dir=tmp_path, env={})
    assert install_session(page, config) is None
    page.goto.assert_not_called()
    _session(tmp_path, obtained_at=0)
    assert install_session(page, config) is None
    page.goto.assert_not_called()


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
        with pytest.raises(Unconfirmed, match='manual handling'):
            play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)
        click.assert_not_called()


def test_doc_and_image_items_open_their_viewer_with_dwell(tmp_path):
    browser, _ = setup_browser()
    data = {'progress': '', 'items': [{'id': 'd', 'type': '1', 'st': '未开始', 'opt': False},
                                      {'id': 'i', 'type': '2', 'st': '未开始', 'opt': False},
                                      {'id': 'u', 'type': '3', 'st': '未开始', 'opt': False}]}
    calls = []
    config = load_config(data_dir=tmp_path, item_dwell_seconds=15, env={})
    with patch('wangda.adapter.read_subject', return_value=data), \
            patch('wangda.adapter.confirm_subject', return_value=data), \
            patch.object(engine, 'click_item', side_effect=lambda *a, **k: calls.append((a[1], k))):
        result = play(browser, config, SUBJECT)
    assert result['verified'] is True
    assert [call[0] for call in calls] == ['d', 'i', 'u']
    assert [call[1]['dwell'] for call in calls] == [15, 15, 0]
    assert [call[1]['log_ev'] for call in calls] == ['item_doc', 'item_image', 'item_url']


def test_manual_item_does_not_preempt_a_video(tmp_path):
    browser, _ = setup_browser()
    data = {'progress': '', 'items': [{'id': 'exam', 'type': '9', 'st': '未开始', 'opt': False},
                                      {'id': 'vid', 'type': '10', 'st': '未开始', 'opt': False}]}
    with patch('wangda.adapter.read_subject', return_value=data), \
            patch.object(engine, 'run_course', return_value=True) as run, \
            patch.object(engine, 'log'):
        with pytest.raises(Unconfirmed, match='manual handling: type 9'):
            play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)
    assert run.call_count == 1


def test_subject_continues_after_failed_course_when_configured(tmp_path):
    browser, _ = setup_browser()
    data = {'progress': '', 'items': [{'id': 'a', 'type': '10', 'st': '未开始', 'opt': False},
                                      {'id': 'b', 'type': '10', 'st': '未开始', 'opt': False}]}
    calls = []
    def run_course(page, course_id, subject, rate, logpath):
        calls.append(course_id)
        return course_id == 'b'
    config = load_config(data_dir=tmp_path, continue_on_error=True, env={})
    with patch('wangda.adapter.read_subject', return_value=data), \
         patch.object(engine, 'run_course', side_effect=run_course), \
         patch.object(engine, 'log'):
        with pytest.raises(Unconfirmed):
            play(browser, config, SUBJECT)
    assert calls == ['a', 'b']


def test_subject_stops_after_failed_course_by_default(tmp_path):
    browser, _ = setup_browser()
    data = {'progress': '', 'items': [{'id': 'a', 'type': '10', 'st': '未开始', 'opt': False},
                                      {'id': 'b', 'type': '10', 'st': '未开始', 'opt': False}]}
    calls = []
    def run_course(page, course_id, subject, rate, logpath):
        calls.append(course_id)
        return False
    with patch('wangda.adapter.read_subject', return_value=data), \
         patch.object(engine, 'run_course', side_effect=run_course):
        with pytest.raises(Unconfirmed):
            play(browser, load_config(data_dir=tmp_path, env={}), SUBJECT)
    assert calls == ['a']


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


CERT_CLAIMABLE = {'exists': True, 'claimed': False, 'claimable': True, 'action': '领取证书'}
CERT_CLAIMED = {'exists': True, 'claimed': True, 'claimable': False, 'action': '查看证书'}
CERT_INELIGIBLE = {'exists': True, 'claimed': False, 'claimable': False, 'action': ''}


def certificate_config(tmp_path):
    return load_config(data_dir=tmp_path, confirmation_seconds=0.01, poll_seconds=0.001, env={})


def test_certificate_already_claimed_is_not_clicked(tmp_path):
    browser, page = setup_browser()
    with patch('wangda.adapter.prepare', return_value=page), \
         patch('wangda.adapter.read_certificate_page', return_value=CERT_CLAIMED), \
         patch.object(engine, 'click_certificate') as click:
        result = claim_certificate(browser, certificate_config(tmp_path), SUBJECT)
    assert result == {'status': 'already_claimed', 'subject': 'demo-topic'}
    click.assert_not_called()
    browser.close.assert_called_once()
    page.close.assert_called_once()


def test_certificate_claim_is_reloaded_to_verify_server_state(tmp_path):
    browser, page = setup_browser()
    with patch('wangda.adapter.prepare', return_value=page), \
         patch('wangda.adapter.read_certificate_page', return_value=CERT_CLAIMABLE), \
         patch('wangda.adapter.read_subject'), \
         patch.object(engine, 'certificate_state', side_effect=[CERT_CLAIMED, CERT_CLAIMED]), \
         patch.object(engine, 'click_certificate', return_value='clicked') as click:
        result = claim_certificate(browser, certificate_config(tmp_path), SUBJECT)
    assert result == {'status': 'claimed', 'subject': 'demo-topic'}
    click.assert_called_once()
    page.call.assert_any_call('Page.reload', ignoreCache=True)


def test_certificate_unmet_conditions_are_not_clicked(tmp_path):
    browser, page = setup_browser()
    with patch('wangda.adapter.prepare', return_value=page), \
         patch('wangda.adapter.read_certificate_page', return_value=CERT_INELIGIBLE), \
         patch.object(engine, 'click_certificate') as click:
        with pytest.raises(CertificateUnavailable) as raised:
            claim_certificate(browser, certificate_config(tmp_path), SUBJECT)
        click.assert_not_called()
    assert raised.value.status == 'not_eligible'
    browser.close.assert_called_once()


def test_certificate_missing_entry_is_reported_without_click(tmp_path):
    browser, page = setup_browser()
    with patch('wangda.adapter.prepare', return_value=page), \
         patch('wangda.adapter.read_certificate_page', return_value={'exists': False}), \
         patch.object(engine, 'click_certificate') as click:
        with pytest.raises(CertificateUnavailable) as raised:
            claim_certificate(browser, certificate_config(tmp_path), SUBJECT)
        click.assert_not_called()
    assert raised.value.status == 'no_certificate'


def test_certificate_claim_that_never_confirms_is_bounded(tmp_path):
    browser, page = setup_browser()
    with patch('wangda.adapter.prepare', return_value=page), \
         patch('wangda.adapter.read_certificate_page', return_value=CERT_CLAIMABLE), \
         patch.object(engine, 'certificate_state', return_value=CERT_INELIGIBLE), \
         patch.object(engine, 'click_certificate', return_value='clicked'), \
         patch('wangda.adapter.time.sleep'):
        with pytest.raises(Unconfirmed):
            claim_certificate(browser, certificate_config(tmp_path), SUBJECT)
    page.call.assert_not_called()


def test_certificate_download_runs_only_when_requested(tmp_path):
    browser, page = setup_browser()
    target = tmp_path / 'cert.png'
    with patch('wangda.adapter.prepare', return_value=page), \
         patch('wangda.adapter.read_certificate_page', return_value=CERT_CLAIMED), \
         patch('wangda.adapter.download_certificate', return_value=target) as download:
        result = claim_certificate(browser, certificate_config(tmp_path), SUBJECT,
                                   download_dir=tmp_path / 'certs')
    assert result['status'] == 'already_claimed'
    assert result['downloaded'] is True
    assert result['file'] == str(target)
    download.assert_called_once()
    assert download.call_args.args[1] == Path(tmp_path / 'certs')


def test_read_certificate_page_waits_for_the_target_subject():
    page = Mock()
    hrefs = iter(['https://wangda.chinamobile.com/#/study/subject/detail/other/1',
                  'https://wangda.chinamobile.com/#/study/subject/detail/demo-topic/1'])
    page.js.side_effect = lambda expr: next(hrefs) if expr == 'location.href' else ''
    with patch('wangda.adapter.engine.is_login_wall', return_value=False), \
         patch('wangda.adapter.engine.certificate_state', return_value=CERT_CLAIMED) as state, \
         patch('wangda.adapter.engine.subject_items', return_value={'items': []}), \
         patch('wangda.adapter.time.sleep'):
        assert read_certificate_page(page, 'subject-url', 'demo-topic') == CERT_CLAIMED
    assert state.call_count == 1


def test_wait_for_download_ignores_existing_zero_and_partial_files(tmp_path):
    assert wait_for_download(tmp_path, {}, timeout=0) is None
    (tmp_path / 'partial.png.crdownload').write_bytes(b'x')
    (tmp_path / 'empty.png').write_bytes(b'')
    assert wait_for_download(tmp_path, {}, timeout=0) is None
    (tmp_path / 'old.png').write_bytes(b'old')
    before = download_snapshot(tmp_path)
    assert wait_for_download(tmp_path, before, timeout=0) is None
    (tmp_path / 'new.png').write_bytes(b'png')
    assert wait_for_download(tmp_path, before, timeout=0) == tmp_path / 'new.png'


def test_wait_for_download_detects_a_same_named_overwrite(tmp_path):
    target = tmp_path / 'cert.png'
    target.write_bytes(b'old')
    before = download_snapshot(tmp_path)
    target.write_bytes(b'new-and-longer')
    changed = before['cert.png'][1] + 1_000_000
    os.utime(target, ns=(changed, changed))
    assert wait_for_download(tmp_path, before, timeout=0) == target


def test_download_certificate_opens_dialog_downloads_and_closes(tmp_path):
    page = Mock()
    target = tmp_path / 'cert.png'
    with patch.object(engine, 'certificate_dialog', side_effect=[{'open': False}, {'open': True}]), \
         patch.object(engine, 'click_certificate', return_value='clicked') as open_dialog, \
         patch.object(engine, 'click_certificate_download', return_value='clicked') as download, \
         patch.object(engine, 'close_certificate_dialog') as close, \
         patch('wangda.adapter.wait_for_download', return_value=target):
        assert download_certificate(page, tmp_path) == target
    open_dialog.assert_called_once()
    download.assert_called_once()
    close.assert_called_once()
    page.call.assert_any_call('Browser.setDownloadBehavior', behavior='allow',
                              downloadPath=str(tmp_path.resolve()), eventsEnabled=True)


def test_download_certificate_rejects_a_file_path(tmp_path):
    target = tmp_path / 'not-a-directory'
    target.write_bytes(b'x')
    with pytest.raises(ValueError):
        download_certificate(Mock(), target)


def test_course_run_accepts_a_statusless_subject_layout(tmp_path):
    browser, _ = setup_browser()
    cards = {'progress': '', 'hasStatus': False, 'items': [{'id': 'c1', 'type': '10', 'st': '', 'opt': False}]}
    config = load_config(data_dir=tmp_path, env={})
    with patch.object(engine, 'run_course', return_value=True), \
            patch('wangda.adapter.confirm_subject', side_effect=Unconfirmed('cards not ready')), \
            patch('wangda.adapter.read_subject', return_value=cards), \
            patch.object(engine, 'log'):
        result = play(browser, config, COURSE)
    assert result['verified'] is True
    assert result['confirmation'] == 'course_page'


def test_course_run_still_fails_when_the_subject_page_shows_statuses(tmp_path):
    browser, _ = setup_browser()
    cards = {'progress': '', 'hasStatus': True, 'items': [{'id': 'c1', 'type': '10', 'st': '学习中', 'opt': False}]}
    config = load_config(data_dir=tmp_path, env={})
    with patch.object(engine, 'run_course', return_value=True), \
            patch('wangda.adapter.confirm_subject', side_effect=Unconfirmed('cards not ready')), \
            patch('wangda.adapter.read_subject', return_value=cards), \
            patch.object(engine, 'log'):
        with pytest.raises(Unconfirmed):
            play(browser, config, COURSE)


def test_statusless_layout_skips_the_confirmation_window(tmp_path):
    browser, _ = setup_browser()
    cards = {'progress': '', 'hasStatus': False, 'items': [{'id': 'c1', 'type': '10', 'st': '', 'opt': False}]}
    with patch.object(engine, 'run_course', return_value=True), \
            patch('wangda.adapter.confirm_subject') as confirm, \
            patch('wangda.adapter.read_subject', return_value=cards), \
            patch.object(engine, 'log'):
        result = play(browser, load_config(data_dir=tmp_path, env={}), COURSE)
    confirm.assert_not_called()
    assert result['confirmation'] == 'course_page'
