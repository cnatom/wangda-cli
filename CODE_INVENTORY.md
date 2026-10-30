# Code inventory

- Reuse: real-playback worker, section-state parsing, completion checks and synthetic Node DOM replay tests from the author's local Wangda skill (MIT).
- Extend: page completion handling, URL validation, bounded recovery and status reporting.
- New: package/CLI, portable configuration, browser ownership, persisted queue, supervisor, standard Agent Skill and CI.
- Excluded: personal paths, shell/launchd guard, account/session data, concurrency/blocking experiments and internal training contents.

Authority: `src/wangda/engine.py` owns platform playback logic; `browser.py` owns CDP and browser lifecycle; `runner.py` owns queue lifecycle; `state.py` owns persisted state; `durations.py` owns the course-length cache (`durations.json`, keyed by course id, no expiry); `auth.py` owns the session file and the optional browser-free login protocol; `adapter.py` also owns browser login adoption (`browser_login`) and the read-only duration pass (`plan`); `cli.py` is the only command parser. Certificate entry, claim and download selectors live in `engine.py`; `adapter.py` owns reload-based claim confirmation and download-file detection; the `certificate` command is parsed only in `cli.py`. Do not duplicate them in skills or platform integrations.

Tests: `tests/test_engine_replay.py` replays the worker against a Node DOM stub; `tests/test_subject_items.py` + `tests/subject_items_stub.js` cover the subject-card parser for both layouts; `tests/test_browser_login.py` covers login adoption (stale token, `about:blank`, window closed vs Local Storage written); `tests/test_durations.py` covers the duration cache and the ETA bases.

Documentation: README.md is the project overview and skills.sh entry point; docs/usage.md owns CLI usage, runtime prerequisites and configuration; docs/agent-integration.md covers skill initialization and task control.
