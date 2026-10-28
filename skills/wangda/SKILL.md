---
name: wangda
description: Run and monitor Wangda courses with real playback, and claim completion certificates.
license: MIT
compatibility: Requires wangda-cli, Python 3.11+, Chrome/Chromium, local shell access, and an authorized Wangda account. Manual login needs a graphical browser.
metadata:
  author: cnatom
  version: "0.2.0"
---

# Wangda real playback

Use this skill when the user gives China Mobile Wangda course/subject links and asks to play, queue, resume, check progress, or claim a completion certificate. Do not use it for other learning platforms, examinations, or generating completion records.

## Prerequisites

1. Check and initialize the runtime using the first-use instructions below. Do not launch a learning queue until environment checks pass.
2. Use only the user's authorized account and comply with the platform and employer's learning rules. Playback does not establish comprehension or satisfy obligations to attend personally.
3. Ask the user to run `wanda login` and complete authentication in the dedicated window when needed. Never ask for, type, read, or log their password, phone/SMS code, cookies, or tokens.
4. Preserve the same configuration/data directory for every command in one task. Never use the user's normal browser profile.

## First-use setup

- Check `wanda --version`. If missing, check for uv, Git and Python 3.11+, then run `uv tool install 'git+https://github.com/cnatom/wangda-cli.git'`.
- If uv, Git or compatible Python is missing, report the prerequisite and ask the user to install it. Do not change system packages, shell configuration or privileges automatically. Do not install similarly named PyPI packages.
- If the installed CLI is not on PATH, use its resolved absolute path consistently. `uv tool dir --bin` locates the executable directory; do not edit shell configuration.
- Run `wanda doctor --json`. If Chrome/Chromium is missing, ask the user to install it before proceeding.

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
3. Use `run --background` for long playback. Multiple links are sequential, not concurrent. The detached runner owns the queue and recovery; do not add a second agent timer, cron, or OS guard.
4. Poll `status` at reasonable intervals (for example once per minute or on user request). It reads only the local atomic snapshot. `logs` also reads local files and does not connect to the browser.
5. On `waiting_login`, tell the user to authenticate manually, then explicitly `resume`. Do not auto-retry login or open extra windows.
6. On `paused` or `stopped`, do not resume without the user's intent. On `interrupted`, explain that the runner died; an explicit `resume` rechecks the platform and skips completed queue entries.
7. On `unconfirmed`, report it as unconfirmed. Do not convert it to success, repeatedly replay the task, or click unsupported required item types. Only when the user explicitly says to ignore failures, pass `--continue-on-error` to `run`/`resume`: the queue continues with later links and later required items inside a subject, but failed/unconfirmed entries stay failed and the final status remains `failed`/`unconfirmed`.
8. Only report completion when `status == "completed"` and every queue entry is completed with a verified result. Newly evaluated direct courses require both a full course directory/counter and their exact subject card marked completed (`confirmation: "course_and_subject"`). An increase in total completed items could belong to another course and is not proof. Browser exit code, elapsed time, video end, and local section changes alone are not enough.
9. Completion/pause/stop automatically closes owned automation processes and retains the dedicated login profile. `login` intentionally leaves its window open; use `stop` to close it without deleting login state.

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
- Rates are restricted to 1.0, 1.2, and 1.5; availability still depends on platform/account rules.
- Only video (type 10) and normal URL-item UI clicks (type 3) are supported. Unknown required types need manual review.
- `run` starts a new queue. `resume` retains the saved queue and skips confirmed completed entries. A partial course is resumed according to the platform's saved progress, not a local promise of zero loss.
- Course and subject progress can disagree temporarily. The CLI refreshes card state within the configured confirmation window; expiry means `unconfirmed`, not permission to replay indefinitely or manufacture a result.
- Login needs a visible browser/display. A remote headless-only host must use a secure graphical session for authentication; do not export cookies into chat.
- The OAuth login page runs a devtools detector: a tab whose CDP session is attached is blanked to `about:blank` when the user requests an SMS code, so a `--remote-debugging-port` window cannot finish an SMS login. To authenticate, open the same dedicated profile in a plain Chrome window without that flag, have the user log in there, close it, then run `inspect` or `run` and let the CLI attach. Playback pages are unaffected.
- Logs and profiles are private local data. Do not upload them or paste raw page/network state into issues.

## Verification and output

Command results are JSON with `schema_version: 1`; diagnostics go to stderr. Help/argument-usage messages are plain text. Exit codes: 0 successful command/completed/paused/stopped/claimed/already_claimed, 1 failure, 2 invalid configuration/input, 3 login required, 4 unconfirmed/not_eligible/no_certificate, 5 busy profile.

Certificate results contain the subject id and, when requested, a local `file` path. They never include the certificate image contents or certificate number. Summarize the current task, confirmed progress, outstanding items, and whether it is still running. Separate local playback evidence from platform-confirmed completion. Do not claim that every agent or operating system has been manually tested.
