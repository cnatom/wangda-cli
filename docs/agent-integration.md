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

Certificate claiming is an explicit user action, separate from playback. `wanda certificate '<subject-or-course-url>' --json` clicks only the platform's visible 领取证书 action and confirms the claimed state after a reload. `--download DIR` is opt-in and writes the platform-generated PNG locally. A certificate contains the learner's name and certificate number, so it must stay local. Do not auto-claim, and never retry `not_eligible` or `no_certificate` hoping the platform changes its mind.

Authentication always belongs to the human. On waiting_login: explain the state, have the human complete `wanda login`, and resume after their confirmation. Do not exchange cookie/token files between the agent and user. The OAuth page detects attached devtools sessions and blanks a debug-port tab when an SMS code is requested, so a manual SMS login has to happen in a plain browser window on the dedicated profile; the CLI attaches afterwards. See [usage and configuration](usage.md#登录).

## API contract

See json-contract.md. All command results are JSON by default (`--json` is accepted explicitly). Errors from argparse/help/version are text. Runtime diagnostics go to stderr. Status is the authoritative local run snapshot, while verified course completion originates from the platform page.
