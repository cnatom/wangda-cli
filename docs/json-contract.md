# JSON contract, version 1

Every command result includes `schema_version: 1` and `status`. New optional fields may be added in version 1; clients must tolerate them. A breaking field or meaning change requires a new schema version. Help, version, and argument-usage errors are not command results and remain text.

## Status snapshot

- `status`: idle, running, paused, stopped, waiting_login, interrupted, unconfirmed, failed, completed.
- `run_id`: generated UUID hex for a saved queue.
- `queue`: ordered entries with url, status, attempts; verified completed entries additionally contain result.
- `index`: zero-based current queue position; queue length after completion.
- `owner`: supervisor pid and process creation timestamp.
- `worker_pid`: current child, null after final cleanup.
- `heartbeat_at`, `updated_at`: UTC ISO-8601 supervisor/snapshot times (not proof of playback).
- `progress`: latest tick fields course, idx (zero-based section), v (cur/dur/paused/rate), prog, stat, cnt.
- `last_event`: last sanitized event. Its t is Unix seconds.
- `config`: resolved non-secret execution settings, retained for resume.

From package 0.1.1, a newly evaluated direct-course result additionally includes `confirmation: "course_and_subject"` and `card_status: "已完成"`. Both the course directory/counter and that exact subject card must confirm. Pending or missing cards produce `unconfirmed` (exit 4) after the confirmation window; another card completing does not satisfy it. These fields are additive within schema version 1; old saved results retain their original evidence and are not retroactively rewritten.

A missing snapshot yields idle plus an empty queue. `interrupted` is derived when a saved running owner no longer exists with the same creation time; the status command never writes a repair. A fresh supervisor heartbeat is distinct from advancing video time.

With `--continue-on-error`, every queue entry is attempted even after a failed or unconfirmed item. Those entries keep their `failed`/`unconfirmed` status, and the overall run status is still `failed` or `unconfirmed`; the option never rewrites a failed item as completed. Login, pause and stop remain terminal.

## Certificate result

`certificate` returns `status` plus the resolved `subject` id. `claimed` means this command clicked the platform's visible 领取证书 action and the claimed state survived a reload; `already_claimed` means the entry was already claimed and nothing was clicked. `not_eligible` means the entry exists but its claim conditions are not met; `no_certificate` means the subject page has no certificate entry. The latter two are exit 4 and must not be bypassed.

With `--download DIR`, a successful claim (or an existing claim) also returns `downloaded: true` and `file` with the saved certificate path. The certificate image may contain the learner's name and certificate number; it is never embedded in JSON output or logs.

## Other command statuses

`ready` / `missing_browser` (doctor), `inspected` (inspect), `ok` (logs/skill-path), `error` (invalid input), `busy` (lock conflict). A background startup result is an acknowledgement only, not course completion. Logs returns an events array; skill-path returns an absolute path to SKILL.md.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Successful command, startup acknowledgement, completed, paused, stopped, claimed or already_claimed |
| 1 | Execution failure, failed doctor or unacknowledged control/startup |
| 2 | Invalid arguments/configuration/input |
| 3 | Human login required |
| 4 | Platform completion unconfirmed, unsupported required item, not_eligible or no_certificate |
| 5 | Data/profile owned by another operation |

`status` and `logs` return 0 when the query succeeds, even if the saved run failed. Inspect the JSON status. `run`/`resume` in foreground return the task outcome; background invocations return startup acknowledgement, then clients query status.
