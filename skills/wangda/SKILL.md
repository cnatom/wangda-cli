---
name: wangda
description: Use when playing, resuming, or certifying Wangda courses.
license: MIT
compatibility: Requires wangda-cli, Python 3.11+, Chrome/Chromium, local shell access, and an authorized Wangda account. Manual login needs a graphical browser.
metadata:
  author: cnatom
  version: "0.4.0"
---

# Wangda real playback

Use this skill when the user gives China Mobile Wangda course/subject links and asks to play, queue, resume, check progress, or claim a completion certificate. Do not use it for other learning platforms, examinations, or generating completion records.

## Prerequisites

1. Check and initialize the runtime using the first-use instructions below. Do not launch a learning queue until environment checks pass.
2. Use only the user's authorized account and comply with the platform and employer's learning rules. Playback does not establish comprehension or satisfy obligations to attend personally.
3. Authenticate only through the dedicated profile (see 「Login and profile reuse」). Never ask for, type, read, or log the user's password, phone/SMS code, cookies, or tokens.
4. Preserve the same configuration/data directory **and** `--profile` for every command in one task: a login does not transfer between profiles. Never use the user's normal browser profile.

## First-use setup

- Check `wanda --version`. If missing, check for uv, Git and Python 3.11+, then run `uv tool install 'git+https://github.com/cnatom/wangda-cli.git'`.
- If uv, Git or compatible Python is missing, report the prerequisite and ask the user to install it. Do not change system packages, shell configuration or privileges automatically. Do not install similarly named PyPI packages.
- If the installed CLI is not on PATH, use its resolved absolute path consistently. `uv tool dir --bin` locates the executable directory; do not edit shell configuration.
- Run `wanda doctor --json`. If Chrome/Chromium is missing, ask the user to install it before proceeding.

## Login and profile reuse

Several local profiles can exist (the CLI default, plus any `--profile` used by earlier runs) and cookies live inside one of them. Logging in through the wrong one looks exactly like an expired session.

1. Recover the profile the last queue used before anything else: `wanda status --json` reports it as `config.profile`, and `<data-dir>/run-config.json` holds the same value. Pass that path as `--profile` to **every** later command.
2. `inspect` returning `waiting_login` on a machine that authenticated recently usually means the wrong profile, not an expired session. Compare the recorded profile with the CLI default (`~/Library/Application Support/wangda-cli/profile` on macOS) and re-check with the recorded one before asking the user to log in again.
3. To log in, open the same dedicated profile in a plain Chrome window — no `--remote-debugging-port`, no headless, because the OAuth page blanks a CDP-attached tab as soon as the user requests an SMS code:

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="<recorded-profile>" --no-first-run --no-default-browser-check \
  "https://wangda.chinamobile.com/"
```

Launch it with the shell tool's background mode; shell-level `nohup`/`&` is rejected and leaves the window untracked.
4. Ask the user to finish logging in there, then close that window. The visible window holds the profile lock, so `run`/`inspect` cannot start while it is open. Quit Chrome yourself only after `pgrep -fl "Google Chrome"` shows nothing else running — a global quit closes every Chrome window, including the user's own work.
5. Confirm before queueing: `wanda inspect '<url>' --profile '<recorded>' --json` must return `inspected` with an item list. Only then start work; treat `waiting_login` as "go back to step 3", not as a reason to retry in a loop.

## Commands

Execute commands using the agent's shell tool.

```sh
wanda doctor --json
wanda login
wanda inspect 'https://wangda.chinamobile.com/#/study/subject/detail/EXAMPLE_TOPIC/1' --json
wanda certificate '<subject-or-course-URL>' --json
wanda certificate '<subject-or-course-URL>' --download '<local-directory>' --json
wanda run '<subject-or-course-URL>' --rate 1.5 --background --json
wanda run '<URL-A>' '<URL-B>' --background --json
wanda status --json
wanda logs --tail 10 --json
wanda pause --json
wanda resume --background --json
wanda stop --json
```

The URL above is a placeholder, not a real course. Use the user's exact valid URL, shell-quoted. Global options such as `--data-dir` and `--config` work before or after the command.

## Procedure

1. Read `status` first. If a queue is already running, do not start another or change browser mode.
2. For a new queue, inspect only while no runner owns the profile. Inspection navigates; it is not the running-progress command.
3. Survey every link before queueing: one `inspect` per URL, then count item states (已完成 / 学习中 / 未开始) per subject. This gives the per-subject remaining work and exposes already-complete or unparseable subjects before an hour of playback is committed. Report the survey with the queue.
4. Order the queue so the least understood link is last. A failed entry stops the rest of the queue unless `--continue-on-error` is passed, so put a URL whose survey failed or returned no items at the end instead of relaxing the failure rules.
5. Use `run --background` for long playback. Multiple links are sequential, not concurrent. The detached runner owns the queue and recovery; do not add a second agent timer, cron, or OS guard.
6. Poll `status` at reasonable intervals (for example once per minute or on user request). It reads only the local atomic snapshot. `logs` also reads local files and does not connect to the browser.
7. On `waiting_login`, tell the user to authenticate manually, then explicitly `resume`. Do not auto-retry login or open extra windows.
8. On `paused` or `stopped`, do not resume without the user's intent. On `interrupted`, explain that the runner died; an explicit `resume` rechecks the platform and skips completed queue entries.
9. On `unconfirmed`, report it as unconfirmed. Do not convert it to success, repeatedly replay the task, or click unsupported required item types. Only when the user explicitly says to ignore failures, pass `--continue-on-error` to `run`/`resume`: the queue continues with later links and later required items inside a subject, but failed/unconfirmed entries stay failed and the final status remains `failed`/`unconfirmed`.
10. Only report completion when `status == "completed"` and every queue entry is completed with a verified result. Newly evaluated direct courses require both a full course directory/counter and their exact subject card marked completed (`confirmation: "course_and_subject"`). An increase in total completed items could belong to another course and is not proof. Browser exit code, elapsed time, video end, and local section changes alone are not enough.
11. Completion/pause/stop automatically closes owned automation processes and retains the dedicated login profile. `login` intentionally leaves its window open; use `stop` to close it without deleting login state.

## Certificate claiming

1. Read `status` first. A certificate command is a browser operation; do not run it while a queue owns the profile.
2. If the platform is at the login wall, ask the user to complete `wanda login` themselves. Never request, type, read, or log credentials, SMS codes, cookies, or tokens.
3. Use the user's exact subject or subject-course URL. The command clicks only a visible 领取证书 action; `already_claimed` means nothing was clicked. After a manual login, add `--headed` to reuse that dedicated window instead of switching the profile to headless.
4. Report `claimed` or `already_claimed` as platform-confirmed. `not_eligible` means the certificate conditions are not met and `no_certificate` means the page offers no certificate; do not retry, bypass, or fabricate either outcome.
5. Download only when the user asks. `--download '<directory>'` saves the platform-generated PNG locally. Certificates contain the learner's name and certificate number: never upload, screenshot into chat, or paste their contents.

## Boundaries and pitfalls

- No forged reports, learning-time edits, direct completion-report API calls, account-limit bypass, or parallel sessions for one account.
- Never claim a certificate the platform has not visibly offered, and never modify certificate eligibility or generate a substitute certificate.
- Playback is muted at the browser level (`--mute-audio`) and the player volume is set to 0. Do not unmute it or add audio.
- Background runner and worker processes must not open a visible terminal window. If one appears, stop the queue and restart with the current version.
- `--continue-on-error` is allowed only when the user asks to ignore failures. It never turns a failed/unconfirmed item into completed.
- `inspect` returning `{"status": "failed", "reason": "RuntimeError"}` with no `items` means the subject page produced no item list (unentitled, different layout, or blank page) — not an empty subject. Never report it as complete or as having no required items: queue it last, re-check it once the runner loads it, and report the state as still unknown.
- Rates are restricted to 1.0, 1.2, and 1.5; availability still depends on platform/account rules.
- Only video (type 10) and normal URL-item UI clicks (type 3) are supported. Unknown required types need manual review.
- `run` starts a new queue. `resume` retains the saved queue and skips confirmed completed entries. A partial course is resumed according to the platform's saved progress, not a local promise of zero loss.
- Course and subject progress can disagree temporarily. The CLI refreshes card state within the confirmation window; expiry means `unconfirmed`, not permission to replay indefinitely or manufacture a result.
- Login needs a visible browser/display. A remote headless-only host must use a secure graphical session for authentication; do not export cookies into chat.
- The OAuth login page runs a devtools detector: a tab with an attached CDP session is blanked to `about:blank` when the user requests an SMS code, so a `--remote-debugging-port` window can never finish an SMS login — hence the plain-window procedure in 「Login and profile reuse」. Playback pages are unaffected.
- The platform allows one active course page per account. Opening a course while another session (the user's own browser on another machine, or a leftover tab) holds a course page renders 「您已打开新的课程详情页」 and then blanks the tab to `about:blank`; the CLI reports `error_page_stop` and the whole subject ends `unconfirmed`. Treat it as a concurrency conflict, not a course failure: clicking 继续学习 does not survive the blank, so retrying the queue cannot recover it: ask the user to close Wangda course/study tabs everywhere else, then `resume`.
- Logs and profiles are private local data. Do not upload them or paste raw page/network state into issues.

## Fixing problems: keep improving, deliver by PR

Every problem met during a task is an improvement obligation, not only a status line to report. Diagnose it, then leave the repository better before finishing.

1. Classify it. Skill-level means procedure, pitfall or wording; runtime-level means `src/wangda` logic — an unparsed page layout, a missing state, a JSON contract gap. A symptom whose workaround is already known is skill-level; something the CLI should have handled is runtime-level.
2. Skill-level: record it where the behaviour changes — a 「Boundaries and pitfalls」 entry with the exact symptom string and the recovery action, or the numbered 「Procedure」 step it corrects. Imperative rules, no session narration, no pasted logs.
3. Runtime-level: follow AGENTS.md — failing test in `tests/` first, smallest fix in `src/wangda`, then `uv run pytest -q` and `uv run ruff check src tests`. Keep playback in one implementation; never add a concurrency bypass or a second worker.
4. Deliver by PR, never by pushing `main` directly: branch `fix/<topic>` or `docs/<topic>`, Conventional Commits with one concern per commit, `git push -u origin <branch>`, then `gh pr create` describing scope, symptom, sanitized evidence, tests run and known limits. Merging a green PR is a local decision; publishing, tagging or releasing is not, without the user asking.
5. Do repository work while the runner owns the playback profile. Never re-run `inspect`, `run` or `certificate` to reproduce a live problem: the profile is busy, and a second course page blanks the live session. Read `status`, `logs` and the local snapshot instead, and reproduce offline in a synthetic fixture or the opt-in browser smoke.
6. Close the loop after merge: reinstall with `uv tool install --force 'git+https://github.com/cnatom/wangda-cli.git'`, copy `skills/wangda/` into the agent's skill directory so the loaded skill matches the repository, and re-check `wanda --version`.
7. If the fix is not ready when the task ends, still open the skill-only PR with the pitfall, an explicit 「未修复」 marker and the evidence a later session needs, and tell the user what remains. Never leave the lesson only in the session.
8. Keep credentials, cookies, profiles, real course titles, screenshots and learning logs out of commits, PR bodies and issues. Sanitize command output before quoting it.

## Verification and output

Command results are JSON with `schema_version: 1`; diagnostics go to stderr. Help/argument-usage messages are plain text. Exit codes: 0 successful command/completed/paused/stopped/claimed/already_claimed, 1 failure, 2 invalid configuration/input, 3 login required, 4 unconfirmed/not_eligible/no_certificate, 5 busy profile.

Certificate results contain the subject id and, when requested, a local `file` path. They never include the certificate image contents or certificate number. Summarize the current task, confirmed progress, outstanding items, and whether it is still running. Separate local playback evidence from platform-confirmed completion. Do not claim that every agent or operating system has been manually tested.

Progress reports during a run read the local snapshot — `wanda status --json`, or `scripts/summarize.py` for a one-screen digest — and are answered in compact Chinese: per queue entry status, per subject done/total, the current video `cur/dur` with its rate, remaining work with an explicit unknown where a link's state is unknown, and anything that needs the user (login, a Wangda tab open elsewhere). No raw JSON, no tick-by-tick narration, and offer a reporting cadence instead of going silent.
