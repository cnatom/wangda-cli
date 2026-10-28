# Architecture

## Dependency direction

`cli -> runner/adapter -> browser/engine -> state/config`

More precisely: cli handles parsing and command results; `auth` is a standalone HTTP client used only by the `auth` command (no browser, no platform DOM); runner imports adapter only for URL validation and supervises worker processes; worker calls adapter; adapter calls engine and browser; engine uses browser.Page and an explicitly bound browser for CDP. State and config do not import platform logic. No agent SDK, daemon framework, launchd or shell script is required.

## Single authorities

See CODE_INVENTORY.md. Browser lifecycle is in browser.py, queue lifecycle is in runner.py, persisted state is in state.py, and Wangda DOM selectors/playback are in engine.py. Skill text never contains an alternate worker implementation.

## Queue protocol

A runner holds a data-directory file lock and a canonical profile-path lock. Each URL runs in a fresh Python worker process; one worker at a time, one dedicated browser profile. A run-scoped control file requests pause/stop. Snapshots are replaced atomically. Owner PID plus creation time distinguishes a dead/reused PID; status derives `interrupted` without writing state.

The supervisor saves queue index, attempts, result, last event and current playback snapshot. A zero child exit alone cannot complete an item: a completed+verified result event and zero exit are both required. Completed entries are skipped on explicit resume, partial entries are rechecked on the real platform. Retries reset on explicit resume, with a new run id so old control messages cannot cancel the new run.

The worker emits only JSON events. Unknown/raw stdout is discarded and stderr is not stored. Error messages are reduced to exception class where remote text could expose authentication data. The snapshot/log scrubber redacts sensitive keys, bearer strings, common credential query parameters and JWT-shaped strings. This is defense-in-depth, not permission to log arbitrary page/network contents.

## Recovery

Default heartbeat deadline: 180 seconds. Only playback/subject/confirmation events count as health, not repeated CDP errors. A course also has a finite three-recovery budget for reconnects and stall reloads, so fresh but frozen playback ticks cannot keep reloading forever. Task failures have at most `retries + 1` attempts with interruptible exponential backoff (capped at 30 seconds). Login and unconfirmed results stop immediately.

Stop/pause terminate the current worker and close only browser processes bearing the exact dedicated profile argument, with graceful termination followed by a bounded kill fallback. Profiles are retained. The supervisor is the guard; no recurring OS service remains after completion.

Background mode detaches the supervisor from the invoking agent's process session. It is not a machine-reboot service. After reboot or a force-killed supervisor, run `resume` explicitly. A terminal-wide process-tree killer may still terminate detached processes; inspect status instead of assuming persistence.

After a force-killed supervisor, resume/stop can reap its orphan worker only when both the recorded process creation time and the exact worker module/config-path arguments match. A recycled PID or another command is never signaled. The browser cleanup remains scoped to the dedicated profile.

## Browser and platform boundaries

CDP listens on loopback; dynamic port is read from the dedicated profile's DevToolsActivePort. Local HTTP bypasses proxy settings. A normal browser UA is derived from the installed browser rather than a fixed Mac/version string. Existing compatibility handling for browser dimensions and spurious blank-page redirects is retained; it does not intercept server account-concurrency messages.

No platform frontend bundle or training content is distributed. DOM selectors are maintained in one place. Course completion checks match the current course id, a nonempty directory, completed section labels and a full page counter. Starting in 0.1.1, direct courses also require their exact subject card to show completed; a changed aggregate count is not proof. Subject queues require all required cards to confirm. One shared confirmation helper stops the owned playback timer, pauses the video normally, returns to the subject page, and reloads on pending rechecks because assigning the same SPA hash does not fetch fresh state. The bounded confirmation window ends in unconfirmed, not a replay loop. Type-3 links are clicked only after video sessions end, and unknown types are never guessed.

Only the Wangda web platform is supported. Do not grow a generic platform-plugin framework until a second real integration exists.
