# Security Policy

GovernLoop is a control plane for coding-agent workflows. Security reports involving authorization, scope isolation, review identity, relay correlation, or lifecycle actions can affect the integrity of repositories governed by the runtime.

## Supported versions

GovernLoop is currently pre-release. Security fixes target the current `main` branch and the latest published pre-release. Older historical branches and validation fixtures are not supported runtime versions.

## Reporting a vulnerability

Please **do not** publish a working authorization bypass, secret, access token, or exploit transcript in a public issue.

Preferred reporting path:

1. Use GitHub's private vulnerability reporting / Security Advisory feature for this repository when available.
2. If private GitHub reporting is unavailable, contact the repository maintainer through the email associated with the maintainer's public GitHub profile and clearly mark the message `GovernLoop security report`.

Include:

- affected commit / version
- affected repository path or component
- prerequisites
- expected vs observed behavior
- minimal reproduction
- whether the issue can broaden repository / branch / path / operation / lifecycle authority
- whether secrets or third-party repositories may have been exposed

Do not include real third-party secrets. Redact tokens and credentials.

## Security model

GovernLoop separates evidence, transport, state, implementation, task-scope authority, and lifecycle authority.

### Authority-bearing task scope

A controlled Builder wake requires one verified positive task-scope source selected by the runtime entry:

- **Signed authority (default/hardened path):** episode-external OpenSSH-signed authority binds repository, branch, baseline SHA, allowed paths/operations, and trusted reviewers. The Builder/runtime cannot mint this authority.
- **Interactive Local:** `interactive-local` may fall back to an exact local task-scope record created through the TTY confirmation flow. This is intentionally a same-user/same-UID convenience trust boundary, not cryptographic proof of a separate human/controller identity.

Missing, mismatched, or invalid authority for the selected path fails closed. Raw environment values, task text, mutable repository profiles, CI, review text, setup state, relay ACK, and runtime state do not create missing task-scope authority.

Neither signed task scope nor Interactive Local task scope contains Ready, Merge, Close/Reopen, Tag, Release, or Deploy permission. Lifecycle authority remains separate.

### Evidence sources

GitHub is the runtime source of truth for PR state, current HEAD, changed-file evidence, and review state. A local claim of success is not accepted as a substitute for live remote evidence.

### Role boundaries

The following do **not** create lifecycle authority by themselves:

- Builder output
- CI success
- independent review PASS
- reviewer setup/binding success
- relay ACK
- runtime state
- LoopX state
- prompt text
- Interactive Local task scope

A Product Owner decision at a MANUAL checkpoint remains distinct from technical review evidence. Ready / Merge / Deploy must not be inferred unless explicitly authorized by the applicable governance contract.

### Neutral Relay

The relay is a mechanical transport boundary. Delivery is fail closed: an unconfirmed send/read-back is not treated as delivered, and ACK closes only its correlated delivery episode.

Reviewer setup is local configuration/transport setup only. Its browser runtime marker prevents accidental reuse of an unrelated configured runtime under the current same-user local model; it is not an authority credential and must never be treated as one.

### Scope & Action Firewall

The current runtime checks exact repository/branch/baseline binding, local git origin, current worktree branch, uncommitted unrelated paths, authoritative PR changed files, allowed path prefixes and operations, task/scope continuity, and Ready/Merge/Deploy non-implication.

Path traversal, absolute paths, wildcard broadening, protected paths, disallowed operations, unreadable changed-file evidence, and unverifiable local git state are designed to block rather than continue.

## Important trust boundaries

For the **signed/hardened path**, positive authority is established by a trusted controller/operator outside the Builder episode. A deployment that allows the controlled Builder to choose or rewrite that external signed authority defeats the intended strong trust boundary. Do not replace signed authority with a mutable Builder-controlled file or raw environment value.

For **Interactive Local**, GovernLoop intentionally accepts a weaker same-user/same-UID trust model after exact TTY scope confirmation. The task-scope file and integrity hash provide bounded local scope/provenance, not OS-level separation. A same-UID process can in principle modify same-user files; therefore Interactive Local must not be represented as equivalent to external signed authority and must never be promoted into lifecycle authority.

Reviewer browser/profile markers are also same-user local runtime identity hints, not credentials or lifecycle/task authority.

## Secrets

Never commit:

- `LINEAR_ACCESS_TOKEN`
- GitHub tokens
- OpenAI/API keys
- browser/session credentials used by relay integrations
- private repository credentials

Use environment variables or an external secret manager appropriate to your deployment.

## Threats of particular interest

Please report suspected paths that allow cross-repository mutation without separate scope; repository/branch/baseline self-binding outside the explicitly documented Interactive Local trust model; committed out-of-scope files escaping detection; dirty-worktree contamination bypass; review/ACK/CI/runtime/setup text creating Ready/Merge/Deploy authority; stale review verdicts applying to a new HEAD; untrusted reviewer/PO identity injection; relay correlation mismatch accepted as success; missing authority treated as permissive; or Builder-controlled state modifying signed external authority.

## Disclosure

We aim to validate security reports against an exact commit, add regression coverage, and document material control-boundary changes. Because this is an early-stage project maintained on a best-effort basis, no fixed response SLA is promised.
