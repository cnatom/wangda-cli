"""Platform orchestration. Only visible page state can confirm completion."""
import re
import time
from urllib.parse import urlsplit

from . import engine


class LoginRequired(Exception):
    """Human authentication is required; never retry automatically."""


class Unconfirmed(Exception):
    """The platform has not confirmed completion."""


class UnsupportedItem(Unconfirmed):
    """An item needs manual processing; never guess its behavior."""


ID = r'[A-Za-z0-9_-]+'
SUBJECT_PATH = re.compile(rf'/study/subject/detail/{ID}(?:/\d+)?')
COURSE_PATH = re.compile(rf'/study/course/detail/subject-course/{ID}/6/{ID}')


def validate_url(url):
    if not isinstance(url, str) or any(c.isspace() for c in url):
        raise ValueError('URL must not contain whitespace')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'wangda.chinamobile.com'
            or parsed.path != '/' or parsed.query
            or not (SUBJECT_PATH.fullmatch(parsed.fragment) or COURSE_PATH.fullmatch(parsed.fragment))):
        raise ValueError('Expected a Wangda subject or subject-course HTTPS URL (without credentials/query)')
    return url


def prepare(browser, config):
    engine.BROWSER = browser
    browser.open(headed=config.headed)
    page = browser.page()
    page.call('Page.addScriptToEvaluateOnNewDocument', source=engine.DEVTOOL_GUARD)
    return page


def read_subject(page, url, wait=45):
    page.goto(url, wait=10)
    deadline = time.monotonic() + wait
    while True:
        if engine.is_login_wall(page):
            raise LoginRequired('Run wanda login and complete authentication yourself')
        data = engine.subject_items(page)
        if data.get('items'):
            return data
        if time.monotonic() >= deadline:
            raise Unconfirmed('No visible curriculum: login, access or page layout may have changed')
        time.sleep(1)


def inspect(browser, config, url):
    validate_url(url)
    page = None
    try:
        page = prepare(browser, config)
        subject, course = engine.parse_url(url)
        if course:
            if not engine.ensure_course_page(page, course, subject, None):
                if engine.is_login_wall(page):
                    raise LoginRequired()
                raise Unconfirmed('No visible course directory')
            import json
            return json.loads(page.js(engine.SECTION_STATE))
        return read_subject(page, url)
    finally:
        if page is not None:
            page.close()
        browser.close()


def confirm_subject(page, config, url, course_ids=None):
    """Confirm exact cards, not just a course counter or an aggregate increase."""
    page.js(engine.STOP_PLAYBACK)
    deadline = time.monotonic() + config.confirmation_seconds
    first_read = True
    while True:
        if not first_read:
            # Assigning the same SPA hash does not refresh server-backed card state.
            page.call('Page.reload', ignoreCache=True)
        data = read_subject(page, url)
        first_read = False
        engine.log(None, ev='subject', **data)
        if course_ids is None:
            pending = engine.required_items(data['items'])
        else:
            statuses = {item['id']: item['st'] for item in data['items']}
            pending = [cid for cid in course_ids if statuses.get(cid) != '已完成']
        if not pending:
            return data
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Unconfirmed('Requested items remain unconfirmed on the subject page')
        engine.log(None, ev='confirm_wait')
        time.sleep(min(10, config.poll_seconds * 10, remaining))


def play(browser, config, url):
    validate_url(url)
    page = None
    try:
        page = prepare(browser, config)
        subject, course = engine.parse_url(url)
        if course:
            if not engine.run_course(page, course, subject, config.rate, None):
                if engine.is_login_wall(page):
                    raise LoginRequired()
                raise Unconfirmed('Course directory/counter did not confirm completion')
            subject_url = f'{engine.HOST}/#/study/subject/detail/{subject}'
            confirm_subject(page, config, subject_url, course_ids=(course,))
            return {'verified': True, 'course': course, 'subject': subject,
                    'confirmation': 'course_and_subject', 'card_status': '已完成'}
        data = read_subject(page, url)
        engine.log(None, ev='subject', **data)
        pending = engine.required_items(data['items'])
        # All video sessions finish before link clicks, which can supersede playback sessions.
        ordered = sorted(pending, key=lambda item: item.get('type') != '10')
        for item in ordered:
            if item.get('type') == '10':
                if not engine.run_course(page, item['id'], subject, config.rate, None):
                    if engine.is_login_wall(page):
                        raise LoginRequired()
                    raise Unconfirmed('A required course did not confirm completion')
            elif item.get('type') == '3':
                read_subject(page, url)
                engine.click_item(page, item['id'], None)
            else:
                raise UnsupportedItem('Unsupported required item type: manual review needed')
        data = confirm_subject(page, config, url)
        return {'verified': True, 'subject': subject, 'progress': data['progress'], 'items': data['items']}
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        browser.close()
