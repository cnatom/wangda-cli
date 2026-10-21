# Contributing

Read AGENTS.md, CODE_INVENTORY.md and docs/architecture.md first. Set up Python 3.11+ and Node 20+, then `uv sync --extra dev`.

Write a failing test for the behavior, implement the smallest change, and run `uv run pytest -q` and `uv run ruff check src tests`. Browser smoke tests are opt-in and offline. Do not require a real account or training platform access in CI. See docs/verification.md for authenticated manual acceptance.

Keep playback in one implementation. Do not add framework-specific worker forks, personal paths, global process kills, recurring OS guards or concurrency-bypass code. Update the JSON contract and portable skill when commands change. Include synthetic regression data only.

Open an issue/PR with scope, tests and known limitations. Never upload credentials or internal learning materials.
