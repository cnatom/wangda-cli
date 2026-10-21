# Contributor instructions

- Read README.md, CODE_INVENTORY.md and docs/architecture.md first.
- Keep runtime logic in src/wangda; the skill is instructions only. Do not create a second implementation per agent.
- Use synthetic fixtures only. Never commit profiles, tokens, internal course contents, screenshots or real learning logs.
- No forged learning records, reporting API calls or server-concurrency bypass experiments.
- New behaviors and fixes need failing tests before implementation. Run pytest and ruff; an offline real-browser smoke is opt-in.
- Status/log queries must remain read-only and never attach to or navigate the browser.
- Do not touch a personal browser or another data directory's processes. Preserve login profiles on shutdown.
- Document platform verification honestly: CI is not authenticated live Wangda validation.
- Commits use Conventional Commits. Do not publish or create releases without maintainer authorization.
