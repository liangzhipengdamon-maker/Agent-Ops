# AgentOps v0.1.0 Release Checklist

This checklist separates technical readiness from lifecycle authorization. Checking an item is evidence; it does not by itself authorize merge, tag, release, or deployment.

## 1. Canonical runtime baseline

- [x] AUTO / MANUAL runtime merged to `main`
- [x] deterministic Scope & Action Firewall merged to `main`
- [x] exact-current-HEAD independent review loop demonstrated
- [x] `CHANGES_REQUESTED` -> Builder remediation -> new HEAD -> re-review demonstrated
- [x] MANUAL `WAITING_PO_AUTH` behavior demonstrated
- [x] historical LOW/MEDIUM/HIGH runtime model superseded by canonical rules

Canonical control contract:

`docs/governance/CURRENT_RUNTIME_RULES.md`

## 2. Repository hygiene

- [x] repository visibility is public
- [x] historical validation-only AgentOps PRs closed without merge
- [x] no stale open AgentOps PRs before OSS readiness branch
- [x] public README describes actual maturity and limitations
- [x] current-vs-historical governance boundary is explicit
- [ ] scan public tree/history for accidentally committed secrets or personal machine artifacts
- [ ] verify repository About description/topics are useful to external users

## 3. Open-source community files

- [x] Apache-2.0 `LICENSE`
- [x] `CONTRIBUTING.md`
- [x] `SECURITY.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `CHANGELOG.md`
- [x] detailed `docs/QUICKSTART.md`

## 4. Reproducibility

- [x] production CLI entrypoint documented
- [x] required scope-authority environment documented
- [x] GitHub CLI dependency documented
- [x] Linear token dependency documented
- [x] environment-specific LoopX / Neutral Relay dependencies disclosed
- [ ] run documented quick-start commands in a clean checkout
- [ ] verify no README command depends on an uncommitted local file

## 5. Test and review gate

- [ ] OSS readiness PR CI passes on exact current HEAD
- [ ] independent reviewer reviews actual current OSS readiness PR HEAD
- [ ] all P0/P1 review findings resolved on a new exact HEAD
- [ ] final exact HEAD receives PASS

## 6. Real-world pilot evidence

AGE-37 is the preferred final pilot:

- [x] AGE-6 firewall prerequisite completed
- [x] LearnMind-English target repository identified
- [x] AGE-37 moved to In Progress
- [ ] local Controller/Builder starts the real cross-project pilot
- [ ] exact target repo / branch / baseline / paths / operations recorded
- [ ] isolated LearnMind branch/worktree used
- [ ] Draft LearnMind PR created
- [ ] independent exact-HEAD review delivered automatically
- [ ] remediation loop demonstrated if review requests changes
- [ ] PASS reaches `WAITING_PO_AUTH`
- [ ] no Ready / Merge / Deploy without separate PO authorization

The v0.1.0 release may proceed without claiming this pilot is complete if it remains unavailable; the README and application must then continue to describe cross-project validation as pending.

## 7. Release lifecycle gate

After the OSS readiness PR receives final exact-HEAD PASS:

- [ ] Product Owner explicitly authorizes merge against that exact HEAD
- [ ] merge OSS readiness PR
- [ ] re-read canonical `main`
- [ ] run post-merge CI / smoke checks if applicable
- [ ] Product Owner explicitly authorizes v0.1.0 tag/release
- [ ] create `v0.1.0` tag and GitHub release
- [ ] publish release notes from `CHANGELOG.md`

No automatic deploy is part of v0.1.0.

## 8. Codex for Open Source application

- [x] official application fields reviewed
- [x] repository is public
- [x] applicant is the primary maintainer
- [x] ecosystem-value answer drafted without fabricated adoption metrics
- [x] API-credit use answer drafted
- [x] additional-context answer drafted
- [ ] verify GitHub profile presentation is public/complete
- [ ] fill ChatGPT-account email
- [ ] fill OpenAI Organization ID
- [ ] submit application form
- [ ] record submission date/reference if provided

Application draft:

`docs/CODEX_FOR_OSS_APPLICATION.md`

## 9. Maintenance mode

After v0.1.0:

- [ ] move non-release-critical enhancements to roadmap/backlog
- [ ] keep security / correctness fixes active
- [ ] avoid adding new governance layers without demonstrated need
- [ ] collect real external usage/adoption evidence before making maturity claims
