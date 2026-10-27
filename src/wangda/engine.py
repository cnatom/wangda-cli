"""Wangda DOM adapter migrated from the author's MIT-licensed playback skill.

Completion always requires current visible directory and page counters. No learning-report API is called.
"""
import json
import re
import time

from .browser import Page
from .state import scrub

HOST = "https://wangda.chinamobile.com"
STOP_PLAYBACK = r"""
(() => {
  const worker = window.__wk;
  if (worker && worker.iv) { clearInterval(worker.iv); worker.iv = null; }
  const video = document.querySelector('video');
  if (video) video.pause();
})()
"""
BROWSER = None
EVENT_SINK = None


def http_json(path, method="GET"):
    if BROWSER is None:
        raise RuntimeError("Browser is not configured")
    return BROWSER.http_json(path, method)


def log(path, **kw):
    kw = scrub({**kw, "t": time.time()})
    if EVENT_SINK is not None:
        EVENT_SINK(kw)
    else:
        print(json.dumps(kw, ensure_ascii=False), flush=True)
    if path is not None:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(kw, ensure_ascii=False) + "\n")

WORKER = r"""
(() => {
  const RATE = %RATE%;
  const cidOf = () => ((location.href || '').split('subject-course/')[1] || '').split('/')[0];
  const prev = window.__wk;
  if (prev && prev.iv) clearInterval(prev.iv);      // 清掉旧 worker 的定时器，防止重复执行
  const S = window.__wk = {log: [], n: (prev ? prev.n : 0) + 1, rate: RATE, cid: cidOf(), adv: false, done: false, iv: null};
  try { localStorage.setItem('cache-doubling-speed', String(RATE)); } catch (e) {}
  const secs = () => Array.from(document.querySelectorAll('dl[data-sectiontype]'));
  const txt = (d) => (((d.querySelector('dd') || {}).innerText || '').replace(/\s+/g, ' ').trim());
  const isDone = (d) => /已完成/.test(txt(d));   // dd 文本带类型前缀（「视频 已完成」），不能锚定行首
  const clickSec = (d) => {
    const t = d.querySelector('.start.pointer, .continue.pointer, dt, .course-title');
    (t || d).click();
  };
  let endTicks = 0;
  const step = () => {
    if (window.__wk !== S) { clearInterval(S.iv); return; }   // 被新 worker 取代的旧定时器
    const cid = cidOf();
    if (cid !== S.cid) { S.cid = cid; S.adv = false; endTicks = 0; S.log.push('course_switch'); }
    const list = secs();
    S.cnt = list.length;
    S.stat = list.map(txt);
    const todo = list.map((d, i) => isDone(d) ? -1 : i).filter(i => i >= 0);   // 未完成的节
    S.todo = todo;
    S.done = list.length > 0 && todo.length === 0;      // 每轮从当前目录重算，空目录不算完成
    const cur = list.findIndex(d => d.classList.contains('focus'));
    S.idx = cur;
    const v = document.querySelector('video');
    if (v) {
      S.v = {cur: Math.round(v.currentTime), dur: Math.round(v.duration || 0), paused: v.paused, rate: v.playbackRate};
      v.muted = true;
      v.volume = 0;
      if (Math.abs((v.playbackRate || 1) - S.rate) > 0.01) { try { v.playbackRate = S.rate; } catch (e) {} }
      if (v.paused && !v.ended) { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
    } else {
      S.v = null;
    }
    if (S.done) return;
    const target = todo.length ? todo[0] : -1;
    const atEnd = !!(v && (v.ended || (v.duration > 1 && v.currentTime >= v.duration - 0.6)));
    endTicks = atEnd ? endTicks + 1 : 0;
    const curDone = cur < 0 ? true : isDone(list[cur]);
    // 只在「当前节已完成」或「视频卡在结尾三拍」或「没落在任何节上」时，跳到第一个未完成的节
    if (!S.adv && target >= 0 && target !== cur && (curDone || endTicks >= 3 || cur < 0)) {
      S.adv = true;
      S.log.push('jump#' + (target + 1));
      clickSec(list[target]);
      endTicks = 0;
      setTimeout(() => { S.adv = false; }, 10000);
    }
    const al = document.querySelector('.page-alert');
    if (al && al.offsetParent) { S.log.push('alert'); const b = al.querySelector('button, .btn, a, .confirm'); if (b) b.click(); }
    S.learn = sessionStorage.getItem('course-learn-time');
    S.prog = (document.body.innerText.match(/完成\s*\d+\s*节\s*\/\s*共\s*\d+\s*节/) || [''])[0];
  };
  S.iv = setInterval(step, 2000);
  step();
  return JSON.stringify({idx: S.idx, cnt: S.cnt, todo: S.todo, v: S.v});
})()
"""

SUBJECT_ITEMS = r"""
(() => {
  const out = [];
  document.querySelectorAll('a[data-resource-id]').forEach(b => {
    let root = b;
    for (let i = 0; i < 8 && root; i++) { root = root.parentElement; if (root && root.querySelector('.study-status')) break; }
    const card = root ? (root.innerText || '').replace(/\s+/g, ' ').trim() : '';
    // 平台模板给选修项渲染 <div class="required-tag">选修</div>；必修项没有这个标签。
    // 主判据用 .required-tag，兼容退化时退回卡片文本后缀。
    const tag = root ? root.querySelector('.required-tag') : null;
    const tagText = tag ? (tag.innerText || '').trim() : '';
    out.push({
      id: b.getAttribute('data-resource-id'),
      type: b.getAttribute('data-section-type'),
      st: root ? (root.querySelector('.study-status').innerText || '').trim() : '',
      opt: tag ? /选修/.test(tagText) : /(^|\s)选修\s*$/.test(card)
    });
  });
  const seen = new Set();
  return JSON.stringify({
    progress: (document.body.innerText.match(/完成\s*\d+\s*项\s*\/\s*共\s*\d+\s*项/) || [''])[0],
    items: out.filter(o => !seen.has(o.id) && seen.add(o.id))
  });
})()
"""

DEVTOOL_GUARD = r"""
(() => {
  try {
    try {
      const W = 1280, H = 900;
      Object.defineProperty(window, 'outerWidth', {get: () => W, configurable: true});
      Object.defineProperty(window, 'outerHeight', {get: () => H, configurable: true});
      Object.defineProperty(window, 'outerLeft', {get: () => 0, configurable: true});
      Object.defineProperty(window, 'outerTop', {get: () => 0, configurable: true});
      Object.defineProperty(screen, 'width', {get: () => W, configurable: true});
      Object.defineProperty(screen, 'height', {get: () => H, configurable: true});
      Object.defineProperty(screen, 'availWidth', {get: () => W, configurable: true});
      Object.defineProperty(screen, 'availHeight', {get: () => H - 25, configurable: true});
    } catch (e) {}
    const w = window.open;
    window.__blankBlocked = 0;
    window.open = function (u, n, f) {
      const s = String(u || '');
      if ((s.indexOf('about:blank') === 0 || s === '') && (n === '_self' || !n)) {
        window.__blankBlocked++;
        return null;
      }
      return w.apply(this, arguments);
    };
  } catch (e) {}
})()
"""

SECTION_STATE = r"""
(() => {
  const list = Array.from(document.querySelectorAll('dl[data-sectiontype]'));
  const t = document.body.innerText;
  const cid = ((location.href || '').split('subject-course/')[1] || '').split('/')[0];
  const txt = (d) => (((d.querySelector('dd') || {}).innerText || '').replace(/\s+/g, ' ').trim());
  const wk = window.__wk && window.__wk.cid === cid ? window.__wk : null;
  return JSON.stringify({
    title: document.title,
    href: location.href,
    cid: cid,
    cnt: list.length,
    allDone: list.length > 0 && list.every(d => /已完成/.test(txt(d))),
    prog: (t.match(/完成\s*\d+\s*节\s*\/\s*共\s*\d+\s*节/) || [''])[0],
    st: list.map(d => ((d.querySelector('.start span') || {}).innerText || '').trim()),
    stat: list.map(txt),
    titles: list.map(d => { const q = d.querySelector('.qcontent'); return (q ? (q.getAttribute('title') || q.innerText) : '').trim().slice(0, 30); }),
    todo: wk ? wk.todo : null,
    wk: wk ? {cid: wk.cid, n: wk.n, rate: wk.rate, idx: wk.idx, v: wk.v, learn: wk.learn, log: wk.log} : null
  });
})()
"""

def subject_items(p):
    return json.loads(p.js(SUBJECT_ITEMS))

def parse_url(url):
    """从链接里取 (subject_id, course_id)。"""
    parts = [x for x in url.split("#")[-1].split("/") if x]
    subject = course = None
    if "subject" in parts:
        subject = parts[parts.index("subject") + 2] if len(parts) > parts.index("subject") + 2 else None
    if "subject-course" in parts:
        i = parts.index("subject-course")
        course = parts[i + 1]
        if len(parts) > i + 3:
            subject = parts[i + 3]
    return subject, course

def course_url(course_id, subject_id):
    return f"{HOST}/#/study/course/detail/subject-course/{course_id}/6/{subject_id}"

CREDIT_WAIT_S = 600

TOTAL_RE = re.compile(r"课程总时长\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分钟)?")

def course_total_minutes(text):
    """从课程页正文取「课程总时长 X小时Y分钟」，返回分钟数；取不到返回 None。"""
    m = TOTAL_RE.search(text or "")
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)

RELOAD_LEARN_S = 3300

PROACTIVE_COOLDOWN_S = 1800

def reload_allowed(learn, now, last_reload_at):
    """learn 超阈值也不能每拍重载：重载不会清零 course-learn-time，必须加冷却。"""
    if not need_reload(learn):
        return False
    return (now - last_reload_at) >= PROACTIVE_COOLDOWN_S

def need_reload(learn):
    """防挂机暂停阈值 = 60*pauseTime*1000 - 1000*learn；learn 到 3600 时归零，
    重载不会清零 sessionStorage，只用作有冷却的恢复判据，不修改计数或平台上报。"""
    try:
        return int(learn) >= RELOAD_LEARN_S
    except (TypeError, ValueError):
        return False

RESUME = r"""
(() => {
  const el = Array.from(document.querySelectorAll('a,button,div,span')).find(e =>
    (e.innerText || '').trim() === '继续学习');
  if (el) { el.click(); return 'clicked'; }
  return 'no-button';
})()
"""

CLICK_ITEM = r"""
(() => {
  const b = document.querySelector('a[data-resource-id="%ID%"]');
  if (!b) return 'no-button';
  b.click();
  return 'clicked';
})()
"""

CERTIFICATE_STATE = r"""
(() => {
  const root = document.querySelector('.subject-certificate-entry');
  if (!root) return JSON.stringify({exists: false});
  const link = root.querySelector('.subject-certificate-entry__link');
  const action = link ? (link.innerText || '').replace(/\s+/g, ' ').trim() : '';
  const blocked = !link || link.classList.contains('disabled') ||
                  link.getAttribute('aria-disabled') === 'true';
  const claimed = root.classList.contains('is-claimed');
  return JSON.stringify({
    exists: true,
    claimed: claimed,
    claimable: !claimed && !blocked && /领取/.test(action),
    action: action
  });
})()
"""

CLICK_CERTIFICATE = r"""
(() => {
  const root = document.querySelector('.subject-certificate-entry');
  const link = root ? root.querySelector('.subject-certificate-entry__link') : null;
  if (!link) return 'no-button';
  link.click();
  return 'clicked';
})()
"""

CERTIFICATE_DIALOG_STATE = r"""
(() => {
  const template = document.querySelector('.certificate-x-dialog');
  const dialog = template ? template.closest('.dialog') : null;
  if (!dialog || !dialog.offsetParent) return JSON.stringify({open: false});
  const buttons = Array.from(dialog.querySelectorAll('.dialog-footer .btn'));
  const download = buttons.find(e => (e.innerText || '').trim() === '下载证书');
  return JSON.stringify({
    open: true,
    downloadable: !!download && !download.classList.contains('disabled')
  });
})()
"""

CLICK_CERTIFICATE_DOWNLOAD = r"""
(() => {
  const template = document.querySelector('.certificate-x-dialog');
  const dialog = template ? template.closest('.dialog') : null;
  if (!dialog || !dialog.offsetParent) return 'no-dialog';
  const button = Array.from(dialog.querySelectorAll('.dialog-footer .btn'))
    .find(e => (e.innerText || '').trim() === '下载证书');
  if (!button) return 'no-button';
  if (button.classList.contains('disabled')) return 'disabled';
  button.click();
  return 'clicked';
})()
"""

CLOSE_CERTIFICATE_DIALOG = r"""
(() => {
  const template = document.querySelector('.certificate-x-dialog');
  const dialog = template ? template.closest('.dialog') : null;
  if (!dialog || !dialog.offsetParent) return 'no-dialog';
  const button = Array.from(dialog.querySelectorAll('.dialog-footer .btn'))
    .find(e => (e.innerText || '').trim() === '关闭');
  if (!button) return 'no-button';
  button.click();
  return 'closed';
})()
"""

def certificate_state(p):
    return json.loads(p.js(CERTIFICATE_STATE))

def certificate_dialog(p):
    return json.loads(p.js(CERTIFICATE_DIALOG_STATE))

def click_certificate(p):
    return p.js(CLICK_CERTIFICATE)

def click_certificate_download(p):
    return p.js(CLICK_CERTIFICATE_DOWNLOAD)

def close_certificate_dialog(p):
    return p.js(CLOSE_CERTIFICATE_DIALOG)

def close_new_popups(before_ids):
    """关掉点项按钮后 window.open 出来的外链标签，返回关掉的个数。"""
    n = 0
    for t in http_json("/json/list"):
        if t.get("type") == "page" and t["id"] not in before_ids:
            try:
                http_json("/json/close/" + t["id"])
                n += 1
            except Exception:
                pass
    return n

def click_item(p, item_id, logpath, log_ev="other_item"):
    """URL/文档类必修项：在专题页点它的按钮，平台自己的 url-progress 记完成（不进学习会话）。"""
    before = {t["id"] for t in http_json("/json/list")}
    r = p.js(CLICK_ITEM.replace("%ID%", item_id))
    time.sleep(4)
    n = close_new_popups(before)
    log(logpath, ev=log_ev, id=item_id, click=r, popups_closed=n)
    return r

def reattach(p, want=None):
    """CDP WebSocket 断了（长跑常见：WS 超时/被踢）时重连到同一批标签里的课程页。"""
    try:
        p.close()
    except Exception:
        pass
    try:
        targets = http_json("/json/list")
    except Exception:
        return None
    for t in targets:
        u = t.get("url") or ""
        if t.get("type") == "page" and "/study/" in u and (want is None or want in u):
            try:
                np = Page(t["webSocketDebuggerUrl"])
                np.call("Page.enable")
                np.call("Runtime.enable")
                np.call("Page.addScriptToEvaluateOnNewDocument", source=DEVTOOL_GUARD)
                # The subject orchestrator keeps this Page reference after a course returns.
                p.ws = np.ws
                p.i = np.i
                return p
            except Exception:
                continue
    return None

def is_login_wall(p):
    """网大会话过期时会跳回 /oauth/ 登录页（手机号+短信验证码），此时只能让用户重新登录。"""
    try:
        href = p.js("location.href") or ""
        if "/oauth/" in href:
            return True
        t = p.js("document.body.innerText.slice(0,800)") or ""
        return "短信验证登录" in t or "获取验证码" in t
    except Exception:
        return False

def ensure_course_page(p, course_id, subject_id, logpath):
    """导航到课程页；先清掉 SPA 残留课程，平台把重复打开判为错误页时点「继续学习」恢复。"""
    url = course_url(course_id, subject_id)

    def reset_page():
        try:
            p.call("Page.navigate", url="about:blank")
        except Exception:
            pass
        time.sleep(1)

    reset_page()
    p.goto(url)
    for attempt in range(4):
        href = p.js("location.href") or ""
        if is_login_wall(p):
            log(logpath, ev="login_required", href=href[:90])
            return False
        if "/study/errors/" in href:
            log(logpath, ev="error_page", href=href[:90], attempt=attempt)
            p.js(RESUME)
            time.sleep(6)
            if "/study/errors/" in (p.js("location.href") or ""):
                p.goto(url)
                continue
        current = parse_url(href)[1]
        if current != course_id:
            # 快速切课后平台可能仍停在上一个自动跳转的课程；强制清空 SPA 再进入目标课程。
            log(logpath, ev="course_mismatch_reset", course=course_id, cid=current, attempt=attempt)
            reset_page()
            p.goto(url)
            time.sleep(5)
            continue
        if p.js("document.querySelectorAll('dl[data-sectiontype]').length") or \
           p.js("!!document.querySelector('video')"):
            return True
        time.sleep(5)
    return False

def run_course(p, course_id, subject_id, rate, logpath, stall_limit=6):
    """播放一门课的全部节。只有当前页课程匹配、当前目录非空且全部节已完成、页面计数 x/x 同时满足才算完成。
    节级完成后页面计数迟迟不到 x/x 的，只等 CREDIT_WAIT_S 秒，超时返回 False 且不输出 course_done。"""
    if not ensure_course_page(p, course_id, subject_id, logpath):
        log(logpath, ev="course_unreachable", course=course_id)
        return False
    rate_now = rate
    p.js(WORKER.replace("%RATE%", str(rate_now)))
    log(logpath, ev="course_start", course=course_id, rate=rate_now)
    try:                       # 记下这门课的总时长，便于排期估算
        total = course_total_minutes(p.js("document.body.innerText"))
        if total is not None:
            log(logpath, ev="course_total", course=course_id, total_min=total)
    except Exception:
        pass
    last = None
    stalls = 0
    advance_at = None
    credit_checked = False
    confirm_at = None
    mismatch = 0
    last_reload_at = time.time()
    recoveries = 0
    while True:
        try:
            st = json.loads(p.js(SECTION_STATE))
        except Exception as e:      # CDP 掉线：重连到同一课程页继续
            log(logpath, ev="cdp_error", err=str(e)[:140])
            recoveries += 1
            if recoveries > 3:
                log(logpath, ev="recovery_exhausted", course=course_id)
                return False
            np = reattach(p, want=f"/subject-course/{course_id}/")
            if np is None:
                log(logpath, ev="cdp_reattach_failed")
                time.sleep(20)
                continue
            p = np
            try:
                p.js(WORKER.replace("%RATE%", str(rate_now)))
            except Exception:
                pass
            time.sleep(5)
            continue
        href = st.get("href") or ""
        if "/oauth/" in href:       # 登录态被踢，立刻收工别空转
            log(logpath, ev="login_required", course=course_id)
            return False
        if "/study/errors/" in href:
            log(logpath, ev="error_page_stop", course=course_id, href=href[:90])
            return False
        if st.get("cid") != course_id:
            mismatch += 1
            log(logpath, ev="course_mismatch", course=course_id, cid=st.get("cid"))
            if mismatch >= 3:
                log(logpath, ev="course_unreachable", course=course_id)
                return False
            if not ensure_course_page(p, course_id, subject_id, logpath):
                return False
            p.js(WORKER.replace("%RATE%", str(rate_now)))
            time.sleep(20)
            continue
        mismatch = 0
        wk = st.get("wk") or {}
        if wk.get("cid") != course_id:      # 旧 worker 尚未切到本课：重新初始化
            p.js(WORKER.replace("%RATE%", str(rate_now)))
            log(logpath, ev="worker_reinit", course=course_id)
        v = wk.get("v") or {}
        idx = wk.get("idx")
        prog = st.get("prog") or ""
        cur = (v.get("cur"), prog)
        log(logpath, ev="tick", course=course_id, idx=idx, v=v, learn=wk.get("learn"), prog=prog,
            stat=st.get("stat"), allDone=st.get("allDone"), cnt=st.get("cnt"))
        m = re.match(r"完成\s*(\d+)\s*节\s*/\s*共\s*(\d+)\s*节", prog)
        page_full = bool(m and m.group(2) != "0" and m.group(1) == m.group(2))
        complete = bool(st.get("allDone")) and (st.get("cnt") or 0) > 0
        if complete and page_full:
            log(logpath, ev="course_done", course=course_id, prog=prog, credited=True, rate=rate_now)
            return True
        if complete:
            confirm_at = confirm_at or time.time()
            if time.time() - confirm_at > CREDIT_WAIT_S:
                log(logpath, ev="course_unconfirmed", course=course_id, prog=prog, credited=False)
                return False
        else:
            confirm_at = None
            # 首节播完（进入第 2 节）后 2 分钟查一次学时（只记录；页面计数器刷新有延迟，
            # 不作为降速依据 —— 课时完成与否在 cmd_run 里按专题页服务端真值判定）
            if idx is not None and idx >= 1 and not credit_checked:
                advance_at = advance_at or time.time()
                if time.time() - advance_at > 120:
                    log(logpath, ev="credit_probe", course=course_id, prog=prog,
                        credited=bool(m and int(m.group(1)) >= 1), rate=rate_now)
                    credit_checked = True
            if reload_allowed(wk.get("learn"), time.time(), last_reload_at):
                last_reload_at = time.time()
                log(logpath, ev="proactive_reload", course=course_id, learn=wk.get("learn"))
                ensure_course_page(p, course_id, subject_id, logpath)
                p.js(WORKER.replace("%RATE%", str(rate_now)))
                last = None
                stalls = 0
            if cur == last:
                stalls += 1
                if stalls >= stall_limit:          # 卡住 → 重载页面续播
                    recoveries += 1
                    if recoveries > 3:
                        log(logpath, ev="recovery_exhausted", course=course_id)
                        return False
                    log(logpath, ev="stall_reload", course=course_id)
                    ensure_course_page(p, course_id, subject_id, logpath)
                    p.js(WORKER.replace("%RATE%", str(rate_now)))
                    stalls = 0
            else:
                stalls = 0
            last = cur
        try:
            p.mouse_move()                      # 防挂机
        except Exception:
            pass
        try:
            p.call("Page.bringToFront")         # 保持课程页在前台，避免静音标签被冻结
        except Exception:
            pass
        _t0 = time.time()
        time.sleep(20)
        slow = time.time() - _t0
        if slow > 90:                           # 一拍远超 20s：渲染进程被节流/冻结
            log(logpath, ev="slow_tick", course=course_id, slept=round(slow, 1))
            ensure_course_page(p, course_id, subject_id, logpath)
            p.js(WORKER.replace("%RATE%", str(rate_now)))
            last = None
            stalls = 0

def required_items(items):
    """只保留「待跑必修项」：跳过已完成项和卡片带「选修」标签的选修项。"""
    return [it for it in items if not it.get("opt") and it.get("st") != "已完成"]
