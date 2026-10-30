"""Platform orchestration. Only visible page state can confirm completion."""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import auth, engine
from .browser import Browser


class LoginRequired(Exception):
    """Human authentication is required; never retry automatically."""


class Unconfirmed(Exception):
    """The platform has not confirmed completion."""


class UnsupportedItem(Unconfirmed):
    """An item needs manual processing; never guess its behavior."""


class CertificateUnavailable(Unconfirmed):
    """The platform does not expose a claimable certificate for this subject."""

    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


ID = r'[A-Za-z0-9_-]+'
SUBJECT_PATH = re.compile(rf'/study/subject/detail/{ID}(?:/\d+)?')
COURSE_PATH = re.compile(rf'/study/course/detail/subject-course/{ID}/6/{ID}')

# Subject-card section types. 10 runs a full course session; the click types open the
# item's own viewer so the platform records it; the rest must stay manual.
# 1/2/6 were observed at *course-section* level (inside a course) in the reference tool,
# so their appearance on a subject card is unverified — the click is still confirmed by
# the card's own state, never by the dwell time.
VIDEO_ITEM = '10'
DWELL_ITEMS = {'1': 'doc', '2': 'image', '6': 'video'}
CLICK_ITEMS = {'3': 'url'}
MANUAL_ITEMS = {'9': 'exam', '14': 'live', '16': 'nested_subject'}


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
    install_session(page, config)
    return page


def install_session(page, config):
    """Adopt a `wanda auth` token: the web app stores exactly this localStorage entry."""
    session = auth.read_session(config.data_dir / auth.SESSION_FILE)
    if not session or not auth.is_fresh(session):
        return None
    page.goto(engine.HOST + '/', wait=6)
    token = json.dumps({'access_token': session['access_token'],
                        'token_type': session['token_type'], 'is_weak_pwd': 'false'})
    page.js(f"localStorage.setItem('token', {json.dumps(token)})")
    return session


def browser_login(config, timeout=600, poll=1.0, settle=3.0):
    """Log in by hand in a plain Chrome window, then adopt what the web app stored.

    The login page refuses to work while a devtools session is attached (it blanks itself), so
    the human login has to run in a window without the debugging port. The CLI therefore opens
    the dedicated profile plainly, waits for that window to be closed, then attaches and reads
    the app's own localStorage entry. A token is adopted only when the app visibly renders
    signed-in content: a leftover token keeps reading fine on a blank page (blank documents
    inherit the opener's origin) while the app itself is still on the login wall.
    """
    browser = Browser(config)
    marker = browser.storage_mtime()
    proc = browser.launch_plain(engine.HOST + '/', headed=True)
    deadline = time.monotonic() + timeout
    # Chrome keeps a process alive after its last window closes, so "the window is gone" cannot be
    # detected from the process alone: the app writing its token into Local Storage also ends the
    # wait, and the leftover process is closed by the attach step below.
    while proc.poll() is None and browser.storage_mtime() <= marker:
        if time.monotonic() >= deadline:
            proc.terminate()
            raise LoginRequired('Login did not complete in time; log in, close the window, and retry')
        time.sleep(poll)
    if proc.poll() is None:
        time.sleep(settle)                        # let the token write flush before taking over
    if proc.poll() is None:
        proc.terminate()
    # The window is gone: attach and read the session the platform itself created.
    browser.open(headed=False)
    page = browser.page()
    try:
        page.goto(engine.HOST + '/#/home', wait=8)
        token = engine.session_token(page)
        if not token or not engine.signed_in(page):
            raise LoginRequired('No signed-in session after the login window closed: log in again')
        session = {'access_token': token['access_token'],
                   'token_type': token.get('token_type') or 'Bearer',
                   'expires_in': auth.DEFAULT_EXPIRES_IN,
                   'obtained_at': int(time.time()),
                   'source': 'browser'}
        auth.write_private_json(config.data_dir / auth.SESSION_FILE, session)
        return session
    finally:
        page.close()
        browser.close()


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


def read_certificate_page(page, url, subject, wait=45):
    """Wait for the target subject (not a stale SPA page) and its certificate entry or curriculum."""
    page.goto(url, wait=10)
    deadline = time.monotonic() + wait
    while True:
        if engine.is_login_wall(page):
            raise LoginRequired('Run wanda login and complete authentication yourself')
        href = page.js('location.href') or ''
        if engine.parse_url(href)[0] == subject:
            state = engine.certificate_state(page)
            if state.get('exists') or engine.subject_items(page).get('items'):
                return state
        if time.monotonic() >= deadline:
            raise Unconfirmed('No visible subject or certificate: login, access or page layout may have changed')
        time.sleep(1)


def plan(browser, config, urls, rate=1.5):
    """Read every course page's own 「课程总时长」: exact remaining time, no playback.

    Opening a course page is enough to read the total, but the platform allows only one course
    page per account at a time, so this must not run while a queue plays (the CLI takes the same
    exclusive lock as `inspect`).
    """
    page = prepare(browser, config)
    courses, missing = [], []
    for url in urls:
        subject, course = engine.parse_url(url)
        page.goto(url, wait=10)
        if engine.is_login_wall(page):
            raise LoginRequired('Run wanda login and authenticate yourself')
        deadline = time.monotonic() + 30
        minutes = None
        while True:
            text = page.js('document.body ? document.body.innerText.slice(0, 4000) : ""') or ''
            minutes = engine.course_total_minutes(text)
            if minutes is not None or time.monotonic() >= deadline:
                break
            time.sleep(1)
        if minutes is None:
            missing.append(url)
            continue
        courses.append({'url': url, 'subject': subject, 'course': course,
                        'minutes': minutes, 'seconds': minutes * 60,
                        'seconds_at_rate': int(round(minutes * 60 / rate))})
    total = sum(item['seconds'] for item in courses)
    return {'rate': rate, 'courses': courses, 'missing': missing,
            'total_seconds': total,
            'total_seconds_at_rate': int(round(total / rate)) if rate else None}


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
            return json.loads(page.js(engine.SECTION_STATE))
        return read_subject(page, url)
    finally:
        if page is not None:
            page.close()
        browser.close()


CERTIFICATE_DIALOG_WAIT_S = 15
CERTIFICATE_DOWNLOAD_WAIT_S = 30


def confirm_certificate(page, config, subject_url):
    """The claim must survive one server-backed reload, not just a local class change."""
    deadline = time.monotonic() + config.confirmation_seconds
    while True:
        if engine.certificate_state(page).get('claimed'):
            break
        if time.monotonic() >= deadline:
            raise Unconfirmed('Certificate claim did not confirm on the subject page')
        time.sleep(max(0.2, min(2, config.poll_seconds)))
    page.call('Page.reload', ignoreCache=True)
    read_subject(page, subject_url)
    if not engine.certificate_state(page).get('claimed'):
        raise Unconfirmed('Certificate claim did not persist after reload')


def download_snapshot(directory):
    """Track names, sizes and mtimes because Chrome overwrites same-named downloads."""
    snapshot = {}
    for path in Path(directory).iterdir():
        try:
            if path.is_file():
                stat = path.stat()
                snapshot[path.name] = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            continue
    return snapshot


def wait_for_download(directory, before, timeout=CERTIFICATE_DOWNLOAD_WAIT_S):
    """Return the newest changed non-empty file; Chrome writes .crdownload while running."""
    deadline = time.monotonic() + timeout
    while True:
        candidates = []
        for path in Path(directory).iterdir():
            if not path.is_file() or path.suffix == '.crdownload':
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 0:
                continue
            if before.get(path.name) != (stat.st_size, stat.st_mtime_ns):
                candidates.append((stat.st_mtime_ns, path))
        if candidates:
            return max(candidates)[1]
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def download_certificate(page, directory):
    directory = Path(directory).expanduser().resolve()
    if directory.exists() and not directory.is_dir():
        raise ValueError('Certificate download path must be a directory')
    directory.mkdir(parents=True, exist_ok=True)
    existing = download_snapshot(directory)
    page.call('Browser.setDownloadBehavior', behavior='allow', downloadPath=str(directory),
              eventsEnabled=True)
    try:
        if not engine.certificate_dialog(page).get('open'):
            if engine.click_certificate(page) != 'clicked':
                raise Unconfirmed('Certificate dialog could not be opened')
            deadline = time.monotonic() + CERTIFICATE_DIALOG_WAIT_S
            while not engine.certificate_dialog(page).get('open'):
                if time.monotonic() >= deadline:
                    raise Unconfirmed('Certificate dialog did not open')
                time.sleep(0.5)
        deadline = time.monotonic() + CERTIFICATE_DIALOG_WAIT_S
        while True:
            clicked = engine.click_certificate_download(page)
            if clicked == 'clicked':
                break
            if clicked in ('no-dialog', 'no-button'):
                raise Unconfirmed('Certificate download action is unavailable')
            if time.monotonic() >= deadline:
                raise Unconfirmed('Certificate download action stayed disabled')
            time.sleep(0.5)
        path = wait_for_download(directory, existing)
        if path is None:
            raise Unconfirmed('Certificate download did not produce a file')
        return path
    finally:
        try:
            engine.close_certificate_dialog(page)
        except Exception:
            pass


def claim_certificate(browser, config, url, download_dir=None):
    """Claim only a certificate the platform already offers; never infer eligibility."""
    validate_url(url)
    page = None
    try:
        page = prepare(browser, config)
        subject, _course = engine.parse_url(url)
        if not subject:
            raise ValueError('Could not resolve the subject id from the URL')
        subject_url = f'{engine.HOST}/#/study/subject/detail/{subject}'
        state = read_certificate_page(page, subject_url, subject)
        if not state.get('exists'):
            raise CertificateUnavailable('no_certificate', 'No certificate entry on the subject page')
        if state.get('claimed'):
            status = 'already_claimed'
        elif state.get('claimable'):
            if engine.click_certificate(page) != 'clicked':
                raise Unconfirmed('Certificate action was not clickable')
            confirm_certificate(page, config, subject_url)
            status = 'claimed'
        else:
            raise CertificateUnavailable('not_eligible', 'Certificate requirements are not met')
        result = {'status': status, 'subject': subject}
        if download_dir is not None:
            path = download_certificate(page, download_dir)
            result.update(downloaded=True, file=str(path))
        return result
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        browser.close()


def confirm_subject(page, config, url, course_ids=None, first=None):
    """Confirm exact cards, not just a course counter or an aggregate increase."""
    page.js(engine.STOP_PLAYBACK)
    deadline = time.monotonic() + config.confirmation_seconds
    data = first
    while True:
        if data is None:
            # Assigning the same SPA hash does not refresh server-backed card state.
            page.call('Page.reload', ignoreCache=True)
            data = read_subject(page, url)
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
        data = None


def statusless_layout(data):
    """True only when the subject page renders no status element at all (专区 布局).

    An empty status text on a page that *does* render `.study-status` is just a delayed
    refresh, so it must keep going through the normal confirmation loop.
    """
    items = (data or {}).get('items') or []
    if not items or (data or {}).get('hasStatus') is not False:
        return False
    return not any((item.get('st') or '').strip() for item in items)


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
            # Read the subject page once and reuse it: a statusless layout is confirmed from the
            # course page directly, which avoids burning the confirmation window on every course.
            data = read_subject(page, subject_url)
            if statusless_layout(data):
                confirmation, card_status = 'course_page', ''
            else:
                confirm_subject(page, config, subject_url, course_ids=(course,), first=data)
                confirmation, card_status = 'course_and_subject', '已完成'
            return {'verified': True, 'course': course, 'subject': subject,
                    'confirmation': confirmation, 'card_status': card_status}
        data = read_subject(page, url)
        engine.log(None, ev='subject', **data)
        pending = engine.required_items(data['items'])
        # All video sessions finish before link clicks, which can supersede playback sessions.
        ordered = sorted(pending, key=lambda item: item.get('type') != VIDEO_ITEM)
        failures, manual = [], []
        for item in ordered:
            kind = str(item.get('type') or '')
            if kind == VIDEO_ITEM:
                if not engine.run_course(page, item['id'], subject, config.rate, None):
                    if engine.is_login_wall(page):
                        raise LoginRequired()
                    if config.continue_on_error:
                        failures.append(item['id'])
                        engine.log(None, ev='course_skipped', course=item['id'], reason='unconfirmed')
                        continue
                    raise Unconfirmed('A required course did not confirm completion')
            elif kind in CLICK_ITEMS or kind in DWELL_ITEMS:
                read_subject(page, url)
                engine.click_item(page, item['id'], None,
                                  log_ev='item_' + (CLICK_ITEMS.get(kind) or DWELL_ITEMS[kind]),
                                  dwell=config.item_dwell_seconds if kind in DWELL_ITEMS else 0)
            else:
                # Never guess an unknown type: finish everything actionable, then report it.
                manual.append(kind or '?')
                engine.log(None, ev='item_manual', id=item['id'], type=kind,
                           label=MANUAL_ITEMS.get(kind, 'unknown'))
        if failures:
            engine.log(None, ev='subject_partial', failed=failures)
            raise Unconfirmed('Required items did not confirm completion; continue_on_error skipped them')
        if manual:
            raise Unconfirmed('Required items need manual handling: type ' + ', '.join(sorted(set(manual))))
        data = confirm_subject(page, config, url)
        return {'verified': True, 'subject': subject, 'progress': data['progress'], 'items': data['items']}
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass
        browser.close()
