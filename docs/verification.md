# Verification and limits

## Automated, no account required

```sh
uv sync --extra dev
uv run pytest -q
uv run ruff check src tests
uv build
uv run twine check dist/*
```

Node.js is required only to run the synthetic DOM replay tests, not at runtime. CI installs Node. Other tests use synthetic local workers and fake processes, including real detached-process pause/resume/stop and watchdog recovery. They do not connect to Wangda or need secrets.

Offline real Chromium smoke (Chrome/Chromium must already be installed):

```sh
WANDA_LIVE_BROWSER=1 uv run pytest tests/test_browser_live.py -q
```

It creates an isolated temporary profile, checks CDP, visible headless DOM and cleanup, without platform navigation or login. On Windows set the environment variable using PowerShell's `$env:WANDA_LIVE_BROWSER = '1'`.

## Authenticated platform acceptance

This standalone release has not yet completed an authenticated end-to-end course on every platform. The migrated core has prior personal-use experience on macOS, but that is not proof of the new package's authenticated behavior. Before unattended use:

1. Use an authorized account and a new dedicated profile; complete login manually.
2. Inspect a short permitted course/subject and compare the visible required-item list.
3. Run one short course, then confirm the platform actually marks it completed.
4. Check a multi-link queue, pause/resume, login expiry and cleanup with the same account.
5. Record OS/browser/package versions, never credentials or training contents.

The CI matrix covers Python 3.11/3.14 on macOS/Linux/Windows. Matrix success validates code and synthetic behavior, not institutional access, live browser playback, or the platform's current DOM. Login requires a graphical display; installing this on a Linux server does not magically provide SMS login.

Known scope: a platform layout/rule change may break selectors; page confirmations can lag; partial-course recovery follows platform progress; no multi-account scheduling, no reboot daemon, no MCP server, no hosted login service, and no automatic learning-record repair.
