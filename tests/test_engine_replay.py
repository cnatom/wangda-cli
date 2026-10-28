import json
import os
import shutil
import subprocess
import tempfile

import unittest
from unittest import mock

from wangda import engine as wanda

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.join(HERE, "wanda_dom_harness.js")
SUBJ = "SUBJ1"
OLD_ID = "OLDCOURSE"
NEW_ID = "NEWCOURSE"
VIDEO = {"currentTime": 0, "duration": 100, "paused": False, "ended": False, "playbackRate": 1}


def course_href(cid):
    return f"{wanda.HOST}/#/study/course/detail/subject-course/{cid}/6/{SUBJ}"


def prog(done, total):
    return f"完成 {done} 节 / 共 {total} 节"


def sec(status, focus=False, title="节"):
    return {"status": status, "focus": focus, "title": title}


def worker(rate):
    return wanda.WORKER.replace("%RATE%", str(rate))


class NodePage:
    """用常驻 node 进程执行真实 WORKER / SECTION_STATE 的 fakeDOM 页面。"""

    def __init__(self):
        self.p = subprocess.Popen(["node", HARNESS], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, encoding="utf-8")

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        if not r.get("ok"):
            raise RuntimeError(r.get("err"))
        return r.get("value")

    def set(self, **state):
        self._send({"op": "set", "state": state})

    def advance(self, ms):
        self._send({"op": "advance", "ms": int(ms)})

    def js(self, expr):
        return self._send({"op": "js", "expr": expr})

    def live_timers(self):
        return self._send({"op": "timers"})

    def goto(self, url, wait=6.0):
        self.set(href=url)

    def mouse_move(self, x=None, y=None):
        pass

    def call(self, method, **params):
        return {}

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)
        self.p.stdout.close()


def state(dom):
    return json.loads(dom.js(wanda.SECTION_STATE))


class NodeCourseStateTests(unittest.TestCase):
    def setUp(self):
        self.dom = NodePage()

    def tearDown(self):
        self.dom.close()

    def test_stale_done_from_previous_course_does_not_leak_after_spa_switch(self):
        d = self.dom
        d.set(href=course_href(OLD_ID), sections=[sec("已完成", True)], body=prog(1, 1), video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        d.set(href=course_href(NEW_ID), sections=[sec("未完成", True), sec("未学习"), sec("学习中")],
              body=prog(0, 3))
        d.advance(6000)
        st = state(d)
        self.assertEqual(st["cid"], NEW_ID)
        self.assertIs(st.get("allDone"), False)
        self.assertEqual(st["cnt"], 3)
        self.assertEqual(st["wk"]["cid"], NEW_ID)
        self.assertEqual(st["todo"], [0, 1, 2])

    def test_empty_directory_is_not_complete(self):
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[], body=prog(0, 0), video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        st = state(d)
        self.assertEqual(st["cnt"], 0)
        self.assertIs(st.get("allDone"), False)

    def test_all_sections_done_in_current_directory_is_complete(self):
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[sec("已完成", True), sec("已完成")], body=prog(2, 2),
              video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        st = state(d)
        self.assertIs(st.get("allDone"), True)
        self.assertEqual(st["cnt"], 2)
        self.assertEqual(st["todo"], [])

    def test_done_with_type_prefix_is_recognized(self):
        """真实目录的 dd 文本带类型前缀（如「视频 已完成」），完成判定不能被前缀挡住。"""
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[sec("视频 已完成", True), sec("视频 已完成")],
              body=prog(2, 2), video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        st = state(d)
        self.assertEqual(st["todo"], [])
        self.assertIs(st.get("allDone"), True)

    def test_mixed_prefix_only_finished_sections_are_done(self):
        d = self.dom
        d.set(href=course_href(NEW_ID),
              sections=[sec("视频 已完成", True), sec("视频 学习中"), sec("视频 未学习")],
              body=prog(1, 3), video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        st = state(d)
        self.assertEqual(st["todo"], [1, 2])
        self.assertIs(st.get("allDone"), False)

    def test_unfinished_wording_is_not_counted_as_done(self):
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[sec("未完成", True), sec("未学习"), sec("学习中")],
              body=prog(0, 3), video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        st = state(d)
        self.assertIs(st.get("allDone"), False)
        self.assertEqual(st["todo"], [0, 1, 2])

    def test_rate_switch_reinitializes_single_worker(self):
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[sec("未完成", True)], body=prog(0, 1), video=VIDEO)
        d.js(worker(1.0))
        d.js(worker(1.5))
        d.advance(4000)
        self.assertEqual(d.live_timers(), 1)
        self.assertEqual(d.js("document.querySelector('video').playbackRate"), 1.5)
        self.assertEqual(d.js("window.__wk.rate"), 1.5)

    def test_worker_mutes_video_and_sets_zero_volume(self):
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[sec("学习中", True)], body=prog(0, 1), video=dict(VIDEO))
        d.js(worker(1.5))
        d.advance(4000)
        self.assertTrue(d.js("document.querySelector('video').muted"))
        self.assertEqual(d.js("document.querySelector('video').volume"), 0)

    def test_stop_playback_clears_own_timer_before_pausing_the_video(self):
        d = self.dom
        d.set(href=course_href(NEW_ID), sections=[sec("学习中", True)], body=prog(0, 1), video=VIDEO)
        d.js("document.querySelector('video').pause = function () { this.paused = true; }")
        d.js(worker(1.5))
        d.js(wanda.STOP_PLAYBACK)
        d.advance(10000)
        self.assertEqual(d.live_timers(), 0)
        self.assertTrue(d.js("document.querySelector('video').paused"))


class ReloadCooldownTests(unittest.TestCase):
    def test_cooldown_blocks_repeat_reloads(self):
        now = 10_000.0
        self.assertFalse(wanda.reload_allowed(3300, now, now))          # 刚重载过
        self.assertFalse(wanda.reload_allowed(3300, now + 1799, now))   # 还在冷却
        self.assertTrue(wanda.reload_allowed(3300, now + 1800, now))
        self.assertFalse(wanda.reload_allowed(3000, now + 9999, now))   # 未超阈值
        self.assertGreaterEqual(wanda.PROACTIVE_COOLDOWN_S, 900, "冷却不能太短，否则反复重载")


class CourseTotalTests(unittest.TestCase):
    def test_parses_hours_minutes_and_minutes_only(self):
        self.assertEqual(wanda.course_total_minutes("课程总时长 3小时38分钟"), 218)
        self.assertEqual(wanda.course_total_minutes("课程总时长 45分钟"), 45)
        self.assertEqual(wanda.course_total_minutes("课程总时长 2小时"), 120)
        self.assertIsNone(wanda.course_total_minutes("没有这个字段"))
        self.assertIsNone(wanda.course_total_minutes(None))


class StaleCoursePage:
    """第一次导航仍停在旧课程，模拟平台自动跳课后的 SPA 残留状态。"""

    def __init__(self, target, wrong):
        self.target = target
        self.wrong = wrong
        self.href = ''
        self.navigations = []
        self.gotos = 0

    def call(self, method, **params):
        if method == 'Page.navigate':
            self.navigations.append(params.get('url'))
            self.href = params.get('url')
        return {}

    def goto(self, url, wait=6):
        self.gotos += 1
        self.href = self.wrong if self.gotos == 1 else self.target

    def js(self, expression):
        if expression == 'location.href':
            return self.href
        if "document.querySelectorAll('dl[data-sectiontype]').length" in expression:
            return 1 if self.href == self.target else 0
        if "!!document.querySelector('video')" in expression:
            return self.href == self.target
        return ''


class CoursePageRecoveryTests(unittest.TestCase):
    def test_stale_spa_course_is_reset_until_the_target_course_loads(self):
        target = f"{wanda.HOST}/#/study/course/detail/subject-course/TARGET/6/SUBJ"
        wrong = f"{wanda.HOST}/#/study/course/detail/subject-course/OLD/6/SUBJ"
        page = StaleCoursePage(target, wrong)
        with mock.patch.object(wanda, 'is_login_wall', return_value=False), \
                mock.patch.object(wanda, 'log'), mock.patch.object(wanda.time, 'sleep'):
            self.assertTrue(wanda.ensure_course_page(page, 'TARGET', 'SUBJ', None))
        self.assertEqual(page.gotos, 2)
        self.assertIn('about:blank', page.navigations)


class ReloadThresholdTests(unittest.TestCase):
    def test_threshold_edges(self):
        self.assertFalse(wanda.need_reload(None))
        self.assertFalse(wanda.need_reload(""))
        self.assertFalse(wanda.need_reload("abc"))
        self.assertFalse(wanda.need_reload(3299))
        self.assertTrue(wanda.need_reload(3300))
        self.assertTrue(wanda.need_reload("3600"))
        self.assertLess(wanda.RELOAD_LEARN_S, 3600, "必须在防挂机阈值归零前重载")


class RunCourseReplayTests(unittest.TestCase):
    """用真实 WORKER（node fakeDOM）+ patch 过的 time 重放 wanda.run_course。"""

    def setUp(self):
        self.dom = NodePage()
        self.tmp = tempfile.mkdtemp()
        self.logpath = os.path.join(self.tmp, "run.jsonl")
        self.start = 1000.0
        self.clock = [self.start]
        self.hooks = []

    def tearDown(self):
        self.dom.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_sleep(self, sec):
        self.clock[0] += sec
        self.dom.advance(int(sec * 1000))
        for h in list(self.hooks):
            h(self.clock[0] - self.start)

    def _run(self, course_id):
        with mock.patch.object(wanda.time, "sleep", side_effect=self._fake_sleep), \
                mock.patch.object(wanda.time, "time", side_effect=lambda: self.clock[0]):
            return wanda.run_course(self.dom, course_id, SUBJ, 1.5, self.logpath)

    def _events(self):
        with open(self.logpath, encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def _stale_previous_course_done(self):
        d = self.dom
        d.set(href=course_href(OLD_ID), sections=[sec("已完成", True)], body=prog(1, 1), video=VIDEO)
        d.js(worker(1.5))
        d.advance(4000)
        d.set(href=course_href(NEW_ID), sections=[sec("未完成", True)], body=prog(0, 1))

    def test_stale_done_with_new_course_0_of_1_runs_to_real_1_of_1(self):
        self._stale_previous_course_done()
        flip = []

        def hook(t):
            if t >= 300 and not flip:
                flip.append(t)
                self.dom.set(sections=[sec("已完成", True)], body=prog(1, 1))
        self.hooks.append(hook)

        ok = self._run(NEW_ID)
        events = self._events()
        done = [e for e in events if e["ev"] == "course_done"]
        self.assertTrue(ok)
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0]["credited"])
        self.assertTrue(flip)
        self.assertGreaterEqual(self.clock[0] - self.start, 300)

    def test_local_done_without_page_count_is_unconfirmed_and_bounded(self):
        self._stale_previous_course_done()

        def hook(t):
            if t >= 300:
                self.dom.set(sections=[sec("已完成", True)])
        self.hooks.append(hook)

        ok = self._run(NEW_ID)
        events = self._events()
        self.assertFalse(ok)
        self.assertEqual([e for e in events if e["ev"] == "course_done"], [])
        self.assertTrue([e for e in events if e["ev"] == "course_unconfirmed"])
        self.assertLess(self.clock[0] - self.start, 300 + wanda.CREDIT_WAIT_S + 120)

    def test_absent_page_counter_times_out_fast_and_reports_reason(self):
        """整课节次已完成但该版页面没有「完成 x 节 / 共 y 节」计数：不得空等满 CREDIT_WAIT_S。"""
        self.dom.set(href=course_href(NEW_ID), sections=[sec("已完成", True)], body="", video=VIDEO)
        result = self._run(NEW_ID)
        events = self._events()
        self.assertFalse(result)
        self.assertEqual(getattr(result, "reason", None), "counter_absent")
        unc = [e for e in events if e["ev"] == "course_unconfirmed"]
        self.assertTrue(unc)
        self.assertEqual(unc[0].get("reason"), "counter_absent")
        self.assertLess(self.clock[0] - self.start, wanda.CREDIT_WAIT_S)

    def test_counter_incomplete_keeps_the_full_credit_wait(self):
        """计数存在但没到 x/x：仍按原规则等满 CREDIT_WAIT_S，不放宽确认口径。"""
        self.dom.set(href=course_href(NEW_ID), sections=[sec("已完成", True)], body=prog(1, 2), video=VIDEO)
        result = self._run(NEW_ID)
        events = self._events()
        self.assertFalse(result)
        self.assertEqual(getattr(result, "reason", None), "counter_incomplete")
        unc = [e for e in events if e["ev"] == "course_unconfirmed"]
        self.assertEqual(unc[0].get("reason"), "counter_incomplete")
        self.assertGreaterEqual(self.clock[0] - self.start, wanda.CREDIT_WAIT_S)

    def test_page_advancing_after_all_done_does_not_replay(self):
        """全部节次完成后平台自动切到下一门课：不得重新进入并从头重播。"""
        self.dom.set(href=course_href(NEW_ID), sections=[sec("已完成", True)], body="", video=VIDEO)
        self.hooks.append(lambda t: t >= 40 and self.dom.set(href=course_href(OLD_ID)))
        result = self._run(NEW_ID)
        events = self._events()
        self.assertFalse(result)
        self.assertEqual(getattr(result, "reason", None), "page_advanced")
        self.assertEqual([e for e in events if e["ev"] == "course_start"], [e for e in events if e["ev"] == "course_start"][:1])
        self.assertEqual([e for e in events if e["ev"] == "course_mismatch_reset"], [])
        self.assertLess(self.clock[0] - self.start, 200)

    def test_error_page_stops_without_resume_click(self):
        self._stale_previous_course_done()
        self.hooks.append(lambda t: t >= 60 and self.dom.set(href=f"{wanda.HOST}/#/study/errors/{NEW_ID}&1"))
        ok = self._run(NEW_ID)
        events = self._events()
        self.assertFalse(ok)
        self.assertTrue([e for e in events if e["ev"] == "error_page_stop"])
        self.assertEqual([e for e in events if e["ev"] == "course_done"], [])

    def test_login_wall_stops_run(self):
        self._stale_previous_course_done()
        self.hooks.append(lambda t: t >= 60 and self.dom.set(href=f"{wanda.HOST}/#/oauth/#login"))
        ok = self._run(NEW_ID)
        events = self._events()
        self.assertFalse(ok)
        self.assertTrue([e for e in events if e["ev"] == "login_required"])
        self.assertEqual([e for e in events if e["ev"] == "course_done"], [])



    def test_repeated_stall_reloads_have_a_finite_budget(self):
        self.dom.set(href=course_href(NEW_ID), sections=[sec("未完成", True)],
                     body=prog(0, 1), video=VIDEO)
        def bounded_sleep(seconds):
            self._fake_sleep(seconds)
            if self.clock[0] - self.start > 500:
                raise AssertionError("Stalled course exceeded the recovery budget")
        with mock.patch.object(wanda.time, "sleep", side_effect=bounded_sleep), \
                mock.patch.object(wanda.time, "time", side_effect=lambda: self.clock[0]):
            ok = wanda.run_course(self.dom, NEW_ID, SUBJ, 1.5, self.logpath, stall_limit=2)
        self.assertFalse(ok)
        self.assertTrue(any(event["ev"] == "recovery_exhausted" for event in self._events()))
        self.assertLess(self.clock[0] - self.start, 500)


class RequiredItemSelectionTests(unittest.TestCase):
    """专题只跑必修：卡片带「选修」标签的项跳过，已完成项也跳过。"""

    def test_skips_elective_even_when_not_started(self):
        items = [
            {"id": "a", "type": "10", "st": "未开始", "opt": False},
            {"id": "b", "type": "10", "st": "未开始", "opt": True},
            {"id": "c", "type": "3", "st": "未开始", "opt": True},
        ]
        self.assertEqual([i["id"] for i in wanda.required_items(items)], ["a"])

    def test_skips_done_required_items(self):
        items = [
            {"id": "a", "type": "10", "st": "已完成", "opt": False},
            {"id": "b", "type": "10", "st": "学习中", "opt": False},
        ]
        self.assertEqual([i["id"] for i in wanda.required_items(items)], ["b"])

    def test_missing_opt_field_is_treated_as_required(self):
        self.assertEqual([i["id"] for i in wanda.required_items([{"id": "a", "st": "未开始"}])], ["a"])


class CertificateDomTests(unittest.TestCase):
    """证书入口只按平台可见状态判断，弹窗按钮必须从外层 .dialog 读取。"""

    def setUp(self):
        self.dom = NodePage()

    def tearDown(self):
        self.dom.close()

    def test_claimable_state_requires_the_claim_action(self):
        self.dom.set(certificate={"exists": True, "claimed": False, "action": "领取证书"})
        state = json.loads(self.dom.js(wanda.CERTIFICATE_STATE))
        self.assertTrue(state["exists"])
        self.assertFalse(state["claimed"])
        self.assertTrue(state["claimable"])

    def test_claimed_state_is_not_claimable(self):
        self.dom.set(certificate={"exists": True, "claimed": True, "action": "查看证书"})
        state = json.loads(self.dom.js(wanda.CERTIFICATE_STATE))
        self.assertTrue(state["claimed"])
        self.assertFalse(state["claimable"])

    def test_missing_certificate_entry_is_reported(self):
        self.dom.set(certificate={"exists": False})
        self.assertEqual(json.loads(self.dom.js(wanda.CERTIFICATE_STATE)), {"exists": False})

    def test_dialog_reads_footer_from_the_outer_dialog(self):
        self.dom.set(certificate={"exists": True, "claimed": True, "action": "查看证书",
                                  "dialogOpen": True, "downloadDisabled": False})
        self.assertEqual(json.loads(self.dom.js(wanda.CERTIFICATE_DIALOG_STATE)),
                         {"open": True, "downloadable": True})
        self.assertEqual(self.dom.js(wanda.CLICK_CERTIFICATE_DOWNLOAD), "clicked")
        self.assertEqual(self.dom.js(wanda.CLOSE_CERTIFICATE_DIALOG), "closed")

    def test_closed_dialog_is_not_clicked(self):
        self.dom.set(certificate={"exists": True, "claimed": True, "action": "查看证书"})
        self.assertFalse(json.loads(self.dom.js(wanda.CERTIFICATE_DIALOG_STATE))["open"])
        self.assertEqual(self.dom.js(wanda.CLICK_CERTIFICATE_DOWNLOAD), "no-dialog")

    def test_disabled_download_is_not_clicked(self):
        self.dom.set(certificate={"exists": True, "claimed": True, "action": "查看证书",
                                  "dialogOpen": True, "downloadDisabled": True})
        self.assertEqual(self.dom.js(wanda.CLICK_CERTIFICATE_DOWNLOAD), "disabled")
