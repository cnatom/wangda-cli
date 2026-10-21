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
            return {'verified': True, 'course': course}
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
        deadline = time.monotonic() + config.confirmation_seconds
        while True:
            data = read_subject(page, url)
            engine.log(None, ev='subject', **data)
            if not engine.required_items(data['items']):
                return {'verified': True, 'subject': subject, 'progress': data['progress'], 'items': data['items']}
            if time.monotonic() >= deadline:
                raise Unconfirmed('Required items remain unconfirmed on the platform')
            engine.log(None, ev='confirm_wait')
            time.sleep(min(10, config.poll_seconds * 10))
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        browser.close()
