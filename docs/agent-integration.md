# Agent integration

The wangda skill manages local playback through the `wanda` CLI. It requires local shell access and a graphical browser for manual login.

## Install the skill

```sh
npx skills add cnatom/wangda-cli --skill wangda
```

Follow the installer's prompts to select the target agent and installation scope. The skill source is `skills/wangda/SKILL.md`.

The skill follows the public Agent Skills format: https://agentskills.io/specification . It uses standard name/description/license/compatibility and string-valued metadata, without product-specific tool allowlists or custom runtime metadata.

## First use

The skill checks the runtime and installs the CLI from this repository using uv when needed. Missing system prerequisites are reported to the user rather than installed silently. See [usage and configuration](usage.md). The agent must not rewrite the task runner, add cron guards, or inject another playback script.

`run --background` returns after the detached supervisor acknowledges ownership. Subsequent `status --json` reads the saved state without touching the website. Wait for an explicit terminal status before reporting completion. Do not run `inspect` during playback; the locks reject it rather than interrupting the course.

Authentication always belongs to the human. On waiting_login: explain the state, have the human complete `wanda login`, and resume after their confirmation. Do not exchange cookie/token files between the agent and user.

## API contract

See json-contract.md. All command results are JSON by default (`--json` is accepted explicitly). Errors from argparse/help/version are text. Runtime diagnostics go to stderr. Status is the authoritative local run snapshot, while verified course completion originates from the platform page.
