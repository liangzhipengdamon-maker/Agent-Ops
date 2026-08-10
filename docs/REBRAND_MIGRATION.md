# GovernLoop Naming Migration

GovernLoop is the public project name starting with v0.1.0.

Because the project had already accumulated substantial pre-release validation under the working name AgentOps, v0.1 keeps a **thin compatibility bridge** rather than rewriting the proven control core solely for cosmetics.

## Canonical v0.1 names

Use these for all new integrations:

| Purpose | Canonical v0.1 name |
|---|---|
| Project | `GovernLoop` |
| Python runtime | `governloop_runtime` |
| Authority env | `GOVERNLOOP_*` |
| Local state root | `~/.governloop/` |
| Reviewer config | `~/.governloop/relay/config.json` |
| Browser profile | `~/.governloop/chrome-profile` |
| Browser runtime name | `GovernLoop` |
| Runtime marker value | `governloop-runtime-v1` |

Example:

```bash
export PYTHONPATH="$PWD/tools"
export GOVERNLOOP_SCOPE_REPOSITORY="owner/repository"
export GOVERNLOOP_AUTHORIZED_BRANCH="governloop/example-task"
export GOVERNLOOP_BASELINE_SHA="<exact-base-sha>"
export GOVERNLOOP_ALLOWED_PATHS="src/,tests/"
export GOVERNLOOP_AUTHORIZED_OPERATIONS="fix,continue,complete"

python -m governloop_runtime setup --repo owner/repository
python -m governloop_runtime run-manual --task-id AGE-123 --repo owner/repository --pr 42
```

## Pre-release compatibility names

Existing local environments may contain:

- `agentops_runtime`
- `AGENTOPS_*`
- `~/.agentops/`
- `AgentOps` browser/runtime labels

These are **not** the public v0.1 API. The GovernLoop runtime temporarily maps canonical authority variables into the already-tested pre-release implementation so existing regression evidence remains useful.

Canonical `GOVERNLOOP_*` values win when both old and new variables are set. Missing canonical/legacy positive authority remains missing; the compatibility layer does not create permissive defaults.

## Local reviewer setup migration

The safest migration is to bind the reviewer again using GovernLoop:

```bash
python -m governloop_runtime setup --repo owner/repository
```

This writes a fresh GovernLoop config under `~/.governloop/`. It does **not** copy ChatGPT passwords, cookies, session tokens, or API keys because the setup system never stores them.

Old `~/.agentops/` files are not deleted automatically. Remove them only after you have verified the GovernLoop setup works for your environment.

## Neutral Relay compatibility

The v0.1 repository remains repository-first. The canonical runtime uses the checked-out `tools/neutral-relay/neutral_relay.py` by default and can be overridden explicitly:

```bash
export GOVERNLOOP_RELAY_BIN="/absolute/path/to/neutral_relay.py"
```

The already-reviewed Neutral Relay still checks one pre-release marker filename internally. GovernLoop therefore writes both a canonical `GOVERNLOOP_MARKER` and a local compatibility marker containing the same `governloop-runtime-v1` value. This does not broaden authority or change conversation identity rules.

## Review protocol compatibility

Some pre-v0.1 machine-readable review markers retain their historical token internally so the exact-HEAD review regression suite is not invalidated by a brand-only change. Treat these as wire-compatibility details, not public branding.

## Repository rename

The intended public repository is:

```text
https://github.com/liangzhipengdamon-maker/GovernLoop
```

The GitHub repository-settings rename is synchronized with the final AGE-40 merge/release gate. Verify the new clone URL and any GitHub redirect behavior after the rename before publishing v0.1.0.

## Removal plan

Do not remove the pre-v0.1 compatibility layer simply because v0.1 ships. Remove it only through an explicit breaking-change issue after external migration evidence exists and the canonical GovernLoop path has equivalent regression coverage.
