# Code inventory

- Reuse: real-playback worker, section-state parsing, completion checks and synthetic Node DOM replay tests from the author's local Wangda skill (MIT).
- Extend: page completion handling, URL validation, bounded recovery and status reporting.
- New: package/CLI, portable configuration, browser ownership, persisted queue, supervisor, standard Agent Skill and CI.
- Excluded: personal paths, shell/launchd guard, account/session data, concurrency/blocking experiments and internal training contents.

Authority: `src/wangda/engine.py` owns platform playback logic; `browser.py` owns CDP and browser lifecycle; `runner.py` owns queue lifecycle; `state.py` owns persisted state; `auth.py` owns the browser-free login protocol and the private session file; `cli.py` is the only command parser. Certificate entry, claim and download selectors live in `engine.py`; `adapter.py` owns reload-based claim confirmation and download-file detection; the `certificate` command is parsed only in `cli.py`. Do not duplicate them in skills or platform integrations.

Documentation: README.md is the project overview and skills.sh entry point; docs/usage.md owns CLI usage, runtime prerequisites and configuration; docs/agent-integration.md covers skill initialization and task control.
