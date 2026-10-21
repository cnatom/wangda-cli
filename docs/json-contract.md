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

A missing snapshot yields idle plus an empty queue. `interrupted` is derived when a saved running owner no longer exists with the same creation time; the status command never writes a repair. A fresh supervisor heartbeat is distinct from advancing video time.

## Other command statuses

`ready` / `missing_browser` (doctor), `inspected` (inspect), `ok` (logs/skill-path), `error` (invalid input), `busy` (lock conflict). A background startup result is an acknowledgement only, not course completion. Logs returns an events array; skill-path returns an absolute path to SKILL.md.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Successful command, startup acknowledgement, completed, paused or stopped |
| 1 | Execution failure, failed doctor or unacknowledged control/startup |
| 2 | Invalid arguments/configuration/input |
| 3 | Human login required |
| 4 | Platform completion unconfirmed or unsupported required item |
| 5 | Data/profile owned by another operation |

`status` and `logs` return 0 when the query succeeds, even if the saved run failed. Inspect the JSON status. `run`/`resume` in foreground return the task outcome; background invocations return startup acknowledgement, then clients query status.
