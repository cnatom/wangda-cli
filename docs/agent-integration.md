# Agent integration

The CLI is the compatibility layer. Any agent that can execute local commands and read JSON can use it, even without native Agent Skills support. A chat-only agent cannot run a browser by itself. No claim is made that every product has been tested.

## Install the skill

Run `wanda skill-path --json` to locate the bundled SKILL.md. Copy its containing `wangda` directory into your agent's documented skill directory, or load that file explicitly. In a checkout the source is `skills/wangda/SKILL.md`. Follow your agent's own install/reload instructions; this project does not hard-code a particular framework's private paths.

The skill follows the public Agent Skills format: https://agentskills.io/specification . It uses standard name/description/license/compatibility and string-valued metadata, without product-specific tool allowlists or custom runtime metadata.

## Without skill support

Ask the agent to read SKILL.md and use `wanda` through its shell tool. The full task runner is already implemented in Python; the model must not rewrite it, add cron guards, or inject its own playback script.

`run --background` returns after the detached supervisor acknowledges ownership. Subsequent `status --json` reads the saved state without touching the website. Wait for an explicit terminal status before reporting completion. Do not run `inspect` during playback; the locks reject it rather than interrupting the course.

Authentication always belongs to the human. On waiting_login: explain the state, have the human complete `wanda login`, and resume after their confirmation. Do not exchange cookie/token files between the agent and user.

## API contract

See json-contract.md. All command results are JSON by default (`--json` is accepted explicitly). Errors from argparse/help/version are text. Runtime diagnostics go to stderr. Status is the authoritative local run snapshot, while verified course completion originates from the platform page.
