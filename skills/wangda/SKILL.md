---
name: wangda
description: Run and monitor Wangda courses with real playback.
license: MIT
compatibility: Requires wangda-cli, Python 3.11+, Chrome/Chromium, local shell access, and an authorized Wangda account. Manual login needs a graphical browser.
metadata:
  author: cnatom
  version: "0.1.1"
---

# Wangda real playback

Use this skill when the user gives China Mobile Wangda course/subject links and asks to play, queue, resume, or check progress. This is a local CLI, not a hosted service. It works without a particular agent framework. Do not use it for other learning platforms, examinations, or generating completion records.

## Prerequisites

1. Confirm `wanda --version` and `wanda doctor --json` work. If missing, ask the user to install `wangda-cli` from the project's documented Git URL or a trusted checkout; do not install unreviewed lookalike packages.
2. Use only the user's authorized account and comply with the platform and employer's learning rules. Playback does not establish comprehension or satisfy obligations to attend personally.
3. Ask the user to run `wanda login` and complete authentication in the dedicated window when needed. Never ask for, type, read, or log their password, phone/SMS code, cookies, or tokens.
4. Preserve the same configuration/data directory for every command in one task. Never use the user's normal browser profile.

## Commands

Execute these using whichever shell/process tool the agent provides. There are no framework-specific tool calls.

```sh
wanda doctor --json
wanda login
wanda inspect 'https://wangda.chinamobile.com/#/study/subject/detail/EXAMPLE_TOPIC/1' --json
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
7. On `unconfirmed`, report it as unconfirmed. Do not convert it to success, repeatedly replay the task, or click unsupported required item types.
8. Only report completion when `status == "completed"` and every queue entry is completed with a verified result. Newly evaluated direct courses require both a full course directory/counter and their exact subject card marked completed (`confirmation: "course_and_subject"`). An increase in total completed items could belong to another course and is not proof. Browser exit code, elapsed time, video end, and local section changes alone are not enough.
9. Completion/pause/stop automatically closes owned automation processes and retains the dedicated login profile. `login` intentionally leaves its window open; use `stop` to close it without deleting login state.

## Boundaries and pitfalls

- No forged reports, learning-time edits, direct completion-report API calls, account-limit bypass, or parallel sessions for one account.
- Rates are restricted to 1.0, 1.2, and 1.5; availability still depends on platform/account rules.
- Only video (type 10) and normal URL-item UI clicks (type 3) are supported. Unknown required types need manual review.
- `run` starts a new queue. `resume` retains the saved queue and skips confirmed completed entries. A partial course is resumed according to the platform's saved progress, not a local promise of zero loss.
- Course and subject progress can disagree temporarily. The CLI refreshes card state within the configured confirmation window; expiry means `unconfirmed`, not permission to replay indefinitely or manufacture a result.
- Login needs a visible browser/display. A remote headless-only host must use a secure graphical session for authentication; do not export cookies into chat.
- Logs and profiles are private local data. Do not upload them or paste raw page/network state into issues.

## Verification and output

Command results are JSON with `schema_version: 1`; diagnostics go to stderr. Help/argument-usage messages are plain text. Exit codes: 0 successful command/completed/paused/stopped, 1 failure, 2 invalid configuration/input, 3 login required, 4 unconfirmed completion, 5 busy profile.

Summarize the current task, confirmed progress, outstanding items, and whether it is still running. Separate local playback evidence from platform-confirmed completion. Do not claim that every agent or operating system has been manually tested.
