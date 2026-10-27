// 测试用 fakeDOM：常驻 node 进程，按行接收 JSON 指令，在同一全局里执行 engine.py 的真实 WORKER / SECTION_STATE。
// 指令：{op:"set",state:{href,sections,body,video}} / {op:"js",expr} / {op:"advance",ms} / {op:"timers"}
const readline = require('readline');

let now = 0, nid = 1, timers = [];
const D = {href: '', sections: [], body: '', video: null, certificate: null, clicks: []};
const storage = {};

function mkSec(s, i) {
  return {
    classList: {contains: c => c === 'focus' && !!s.focus},
    querySelector: sel => {
      if (sel === 'dd') return {innerText: s.status || ''};
      if (sel === '.qcontent') return {innerText: s.title || '', getAttribute: () => s.title || ''};
      return {innerText: s.status || '', click: () => { D.clicks.push(i); }};
    },
    click: () => { D.clicks.push(i); },
  };
}

function certRoot() {
  const c = D.certificate;
  if (!c || !c.exists) return null;
  const link = {
    innerText: c.action || '',
    classList: {contains: () => false},
    getAttribute: () => null,
    click: () => { c.clicks = (c.clicks || []).concat('action'); },
  };
  return {
    className: 'subject-certificate-entry ' + (c.claimed ? 'is-claimed' : 'is-unclaimed'),
    classList: {contains: cl => cl === 'is-claimed' && !!c.claimed},
    querySelector: sel => (sel === '.subject-certificate-entry__link' ? link : null),
  };
}

function certDialog() {
  const c = D.certificate;
  if (!c || !c.dialogOpen) return null;
  const button = (text, disabled) => ({
    innerText: text,
    classList: {contains: cl => cl === 'disabled' && !!disabled},
    click: () => { c.clicks = (c.clicks || []).concat(text); },
  });
  const buttons = [button('关闭', false), button('下载证书', !!c.downloadDisabled)];
  return {
    offsetParent: {},
    querySelectorAll: sel => (sel === '.dialog-footer .btn' ? buttons : []),
  };
}

function certTemplate() {
  return {closest: sel => (sel === '.dialog' ? certDialog() : null)};
}

globalThis.window = globalThis;
globalThis.document = {
  title: 'fake',
  querySelectorAll: sel => (sel.indexOf('dl[data-sectiontype]') >= 0 ? D.sections.map(mkSec) : []),
  querySelector: sel => {
    if (sel === 'video') return D.video;
    if (sel === '.subject-certificate-entry') return certRoot();
    if (sel === '.certificate-x-dialog') return D.certificate ? certTemplate() : null;
    return null;
  },
  body: {get innerText() { return D.body; }},
};
globalThis.location = {get href() { return D.href; }};
globalThis.localStorage = globalThis.sessionStorage = {
  getItem: k => (k in storage ? storage[k] : null),
  setItem: (k, v) => { storage[k] = String(v); },
};
globalThis.setInterval = (fn, ms) => { const t = {id: nid++, fn, ms, at: now + ms, live: true}; timers.push(t); return t.id; };
globalThis.setTimeout = (fn, ms) => { const t = {id: nid++, fn, ms: 0, at: now + ms, live: true}; timers.push(t); return t.id; };
globalThis.clearInterval = globalThis.clearTimeout = id => {
  const t = timers.find(x => x.id === id);
  if (t) t.live = false;
};

function advance(ms) {
  const end = now + ms;
  for (;;) {
    let next = null;
    for (const t of timers) if (t.live && t.at <= end && (!next || t.at < next.at)) next = t;
    if (!next) break;
    now = next.at;
    if (next.ms) next.at += next.ms; else next.live = false;
    next.fn();
  }
  now = end;
  timers = timers.filter(t => t.live);
}

const rl = readline.createInterface({input: process.stdin});
rl.on('line', line => {
  let out;
  try {
    const m = JSON.parse(line);
    if (m.op === 'set') {
      Object.assign(D, m.state);
      if (D.video && !D.video.play) D.video.play = () => {};
      out = {ok: true};
    } else if (m.op === 'advance') {
      advance(m.ms);
      out = {ok: true};
    } else if (m.op === 'js') {
      out = {ok: true, value: (0, eval)(m.expr)};
    } else if (m.op === 'timers') {
      out = {ok: true, value: timers.filter(t => t.live).length};
    } else {
      out = {ok: false, err: 'unknown op'};
    }
  } catch (e) {
    out = {ok: false, err: String(e && e.stack || e)};
  }
  process.stdout.write(JSON.stringify(out) + '\n');
});
