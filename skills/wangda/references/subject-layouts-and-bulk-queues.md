# Subject layouts and bulk course queues

Depth notes for the cases where a subject page does not look like the standard
curriculum list. Read this before queueing a 专区-style subject, or when
`inspect` parses some subjects but fails on others.

## Item types live at two different levels

Do not reuse one type table for both levels: they overlap numerically and mean
different things.

| Level | Types seen | Handled by |
|---|---|---|
| Subject card | `10` course, `3` URL, `9` exam, `14` live, `16` nested subject | `adapter.py` (`play`) |
| Course section | `1` 文档, `2` 图片, `6` 视频 | in-page worker in `engine.py` |

A reference tool's `sectionType` map usually describes course sections. Applying
it to subject cards creates unverifiable branches; observed subject pages so
far carry only `10` and `3`. Course sections are advanced by the in-page worker,
which clicks whatever is not 已完成 regardless of type, so doc/image sections
inside a course need no per-type code.

## Completion evidence hierarchy

1. Course page counter 「完成 X 节 / 共 Y 节」 — preferred, but some courses never
   render it.
2. Every section row showing 已完成 on two consecutive ticks — the fallback when
   the counter is absent. One tick is not enough: a half-rendered directory looks
   complete.
3. Subject card showing 已完成 — only exists on the standard layout.
4. `confirmation: course_page` — recorded when the subject page has no status
   element at all; the course page from step 1/2 is the evidence.

An empty status **text** is not the same as a missing status **element**. Ask the
parser whether `.study-status` exists (`hasStatus`), otherwise delayed refreshes
are mistaken for a statusless layout and every course gets confirmed early.

## Standard vs 专区 layout

| | Standard | 专区 |
|---|---|---|
| Status element | `.study-status` present | absent |
| Card text | 已完成 / 学习中 / 未开始 | only 开始学习 or 继续学习 |
| Card click | opens the lesson | no visible effect |
| Confirmation | card state | course page only (`course_page`) |
| Bulk approach | one `run` on the subject | one entry per course |

Clicking a 专区 card's 开始学习 through `element.click()` does nothing (no
navigation, no video). Open the course URL directly instead.

## Bulk queue for a statusless subject

```sh
wanda inspect '<subject-url>' --json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(f\"https://wangda.chinamobile.com/#/study/course/detail/subject-course/{i['id']}/6/<subjectId>\") for i in d['data']['items']]" \
  > /tmp/courses.txt

wanda run $(cat /tmp/courses.txt | tr '\n' ' ') \
  --watch --watch-interval 600 --continue-on-error --background --json
```

`items[].id` is the course id; the subject id is the tail of the subject URL.
Keep `--continue-on-error` so one awkward course cannot starve the rest, and
`--watch` so a temporarily unconfirmed course is retried on the next pass.

Do not plan the run around the declared four-hour token lifetime. The runner asks
the platform once with a read-only profile GET when the declared window passes
and keeps playing if the token is still accepted (`session_note:
declared_expired_but_accepted`); only a real 401/403 parks the queue. When it
does park, the queue continues by itself after `wanda login` / `wanda auth` while
the runner is alive — no `resume` needed. Once `session_wait_seconds` (default 6h)
runs out the runner exits as `waiting_login`: the queue survives, but a `resume`
is then required. Raise `session_wait_seconds` for an overnight queue so an
unattended park does not become an exit.

## Pre-flight: exact durations for a bulk queue

`run` prefetches each course's own 「课程总时长」 before playback (`plan_durations`
default on, `--no-plan-durations` to skip), stores it in `<data-dir>/durations.json`
keyed by course id with no expiry — course lengths do not change — and `status`
then reports the remaining time from those values instead of a pace estimate
(`eta.basis: measured_durations`). `--refresh-durations` re-reads the pages.

- It only fetches what this run will actually play: subject URLs are expanded
  first, completed and optional items are skipped, unreadable pages are left
  unknown and the ETA falls back to the run's observed pace.
- It needs the profile exclusively and the platform allows one course page per
  account, so prefetch is serial and happens **before** playback. Anything that
  wants a read-only pass on demand uses `wanda plan '<urls>' --rate 1.5`, which
  is refused while a queue runs — never open a course page next to a live queue
  to "just check" a length.
- A paused or partly played course still contributes its full length: prefetch reads the course total, not the platform's saved position. Quote `eta` as an upper bound for that entry instead of a finishing time you can promise.

## Text fields are rendered with punctuation

The page writes `课程总时长: 1小时47分钟`, on the same line as `上线时间: …`. A
parser that only allows whitespace between the label and the value (`课程总时长\s*`)
returns nothing at all. Allow an optional `[:：]` and search the whole body text,
not one line; the same regex feeds the course-credit window, so a miss there is
silent rather than loud.

## Diagnosing `inspect` → `{"status":"failed","reason":"RuntimeError"}`

1. Count the cards: `document.querySelectorAll('a[data-resource-id]').length`.
2. If cards exist, the parser is the problem (usually a null deref on a status
   lookup) — fix `SUBJECT_ITEMS`, do not touch the URL.
3. If the count is zero, the page is unentitled, blank or a different layout:
   report the subject as unknown, queue it last, and never report it as complete
   or as having no required items.

A minimal Node DOM stub (no browser) is enough to pin a parser fix: feed the
real `SUBJECT_ITEMS` expression a fake `document` with one standard card, one
statusless card and one optional card, and assert the parsed fields.
