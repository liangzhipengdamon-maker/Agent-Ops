# GovernLoop v0.1.0 Release Checklist

This checklist separates technical readiness evidence from lifecycle authorization. A checked item does not itself authorize tag, GitHub Release, deployment, PyPI publication, or submission of an external application.

## 1. Canonical runtime and governance baseline

- [x] AUTO / MANUAL runtime merged to `main`
- [x] deterministic Scope & Action Firewall merged to `main`
- [x] exact-current-HEAD independent review loop demonstrated
- [x] `CHANGES_REQUESTED` -> remediation -> new HEAD -> re-review demonstrated
- [x] external signed positive-authority model merged and independently reviewed
- [x] trusted-reviewer authority has no mutable profile fallback
- [x] accepted completion requires exact-bound external signed evidence
- [x] MANUAL lifecycle firewall and decide-first Watcher behavior merged and independently reviewed
- [x] historical LOW/MEDIUM/HIGH model superseded by the canonical AUTO / MANUAL contract

Canonical control contract: `docs/governance/CURRENT_RUNTIME_RULES.md`

## 2. GovernLoop public identity

- [x] public name: **GovernLoop**
- [x] tagline: **Governed autonomy for coding agents.**
- [x] repository renamed to `liangzhipengdamon-maker/GovernLoop`
- [x] repository is public; default branch is `main`
- [x] canonical runtime namespace is `governloop_runtime`
- [x] canonical local state root is `~/.governloop/`
- [x] pre-v0.1 AgentOps names are compatibility/history only
- [x] final public repository URL verified during release-readiness audit

## 3. Public repository hygiene

- [x] no open PRs at the AGE-48 release-readiness audit point
- [x] public README describes actual maturity and limitations
- [x] current-vs-historical governance boundary is explicit
- [x] Apache-2.0 `LICENSE`
- [x] `CONTRIBUTING.md`
- [x] `SECURITY.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `CHANGELOG.md`
- [x] detailed `docs/QUICKSTART.md`
- [x] naming migration guide
- [ ] final maintainer check for accidentally committed secrets or personal-machine artifacts before tag creation
- [ ] final repository About/profile presentation check before external application submission

## 4. Installation, onboarding, and reproducibility

- [x] repository-checkout package metadata exists in `pyproject.toml`
- [x] canonical `governloop` console entry point exists
- [x] CI smoke-tests `python -m pip install .`, installed `governloop --help`, and installed imports
- [x] first-run reviewer setup is documented
- [x] guided read-only `governloop doctor` is implemented and documented
- [x] doctor returns one dependency-ordered `next_required_action` or `next_required_external_action`
- [x] clean-room Local Agent cold-start acceptance completed: clone/install -> doctor -> one external action -> safe stop
- [x] missing external signed authority does not produce a Builder self-authority path
- [x] GitHub CLI dependency is documented
- [x] Linear is documented as the current task adapter
- [x] environment-specific browser / Neutral Relay / LoopX dependencies are disclosed

## 5. Latest technical evidence on current main

Canonical main at the AGE-48 issue-creation audit point:

`db55af82cd9af8540907a7814ce6d158d20771ec`

- [x] AGE-40 public rebrand/naming work merged
- [x] AGE-43 canonical exact-bound review protocol merged
- [x] AGE-44 external signed authority / reviewer / completion hardening merged
- [x] AGE-45 MANUAL lifecycle hardening merged
- [x] AGE-46 first-time doctor and baseline-history fail-close merged
- [x] AGE-47 guided bootstrap / installation UX merged
- [x] PR #44 exact HEAD received independent PASS
- [x] PR #44 CI #229 succeeded, including installed CLI smoke
- [x] clean-room first-time-user cold-start acceptance passed after AGE-47 merge

## 6. Cross-project evidence

A full real cross-project pilot may provide useful additional evidence, but v0.1.0 does not claim that such a pilot is complete unless independently recorded as such.

- [x] cross-project isolation and authority boundaries have dedicated fail-closed tests
- [ ] optional real external-project pilot may be completed as follow-up evidence

This optional item is not presented as completed release evidence and is not required to claim only the capabilities actually validated above.

## 7. AGE-48 release-truth finalization gate

Before requesting v0.1.0 tag/release authorization:

- [ ] AGE-48 documentation-only implementation is complete on an exact HEAD
- [ ] changed-file set remains limited to release-facing documentation allowed by AGE-48
- [ ] CI passes if triggered for the finalization PR
- [ ] independent reviewer verifies release truth against current `main`
- [ ] all P0/P1 findings are closed on the reviewed exact HEAD
- [ ] AGE-48 receives final exact-HEAD PASS
- [ ] Product Owner separately authorizes AGE-48 Ready/Merge
- [ ] after merge, re-read canonical `main`
- [ ] read-only v0.1.0 Release Readiness Final Gate returns `READY_FOR_V0.1.0`

## 8. Remaining release lifecycle actions

Only after the final read-only readiness gate returns `READY_FOR_V0.1.0`:

- [ ] Product Owner explicitly authorizes `v0.1.0` Tag + GitHub Release against the exact canonical main/release target
- [ ] create `v0.1.0` tag
- [ ] create GitHub Release
- [ ] publish release notes consistent with `CHANGELOG.md`

No automatic deploy is part of v0.1.0. PyPI publication is not part of this checklist unless separately planned and authorized.

## 9. Codex / Open Source application

These actions are separate from the v0.1.0 tag/release lifecycle:

- [x] repository is public at the final GovernLoop URL
- [x] applicant is the primary maintainer
- [x] ecosystem-value answer is drafted without fabricated adoption metrics
- [x] API-credit use answer is drafted
- [x] additional-context answer is drafted
- [x] worksheet uses GovernLoop branding and final repository identity
- [ ] verify GitHub profile presentation
- [ ] fill ChatGPT-account email
- [ ] fill OpenAI Organization ID
- [ ] review current program form/terms before submission
- [ ] submit the application manually
- [ ] record submission date/reference if provided

Application worksheet: `docs/CODEX_FOR_OSS_APPLICATION.md`

## 10. Post-v0.1.0 maintenance

- [ ] move non-release-critical enhancements to roadmap/backlog
- [ ] keep security/correctness fixes active
- [ ] avoid new governance layers without demonstrated need
- [ ] collect real external usage/adoption evidence before stronger maturity claims
- [ ] remove pre-v0.1 naming compatibility only through an explicit breaking-change plan
