# GovernLoop v0.1.0 Release Checklist

This checklist separates technical readiness from lifecycle authorization. Checking an item is evidence; it does not authorize merge, repository rename, tag, release, or deployment.

## 1. Canonical runtime baseline

- [x] AUTO / MANUAL runtime merged to `main`
- [x] deterministic Scope & Action Firewall merged to `main`
- [x] exact-current-HEAD independent review loop demonstrated
- [x] `CHANGES_REQUESTED` -> Builder remediation -> new HEAD -> re-review demonstrated
- [x] MANUAL `WAITING_PO_AUTH` behavior demonstrated
- [x] historical LOW/MEDIUM/HIGH runtime model superseded
- [x] first-run ChatGPT reviewer binding wizard merged to `main`

Canonical control contract:

`docs/governance/CURRENT_RUNTIME_RULES.md`

## 2. GovernLoop naming freeze

- [x] public name selected: **GovernLoop**
- [x] tagline selected: **Governed autonomy for coding agents.**
- [x] canonical runtime namespace added: `governloop_runtime`
- [x] canonical authority environment documented: `GOVERNLOOP_*`
- [x] canonical local state root documented: `~/.governloop/`
- [x] canonical browser runtime name/marker defined as GovernLoop
- [x] pre-v0.1 naming compatibility strategy documented
- [ ] AGE-40 exact HEAD receives independent PASS
- [ ] Product Owner authorizes AGE-40 merge against exact HEAD
- [ ] merge AGE-40
- [ ] rename GitHub repository `Agent-Ops` -> `GovernLoop` in repository settings
- [ ] verify new repository URL/clone URL and old-URL redirect after rename

The repository slug rename is a GitHub settings mutation and is intentionally synchronized with the final AGE-40 merge so `main` and the public URL change together.

## 3. Repository hygiene

- [x] repository visibility is public
- [x] historical validation-only PRs closed without merge
- [x] public README describes actual maturity and limitations
- [x] current-vs-historical governance boundary is explicit
- [ ] scan public tree/history for accidentally committed secrets or personal machine artifacts
- [ ] verify repository About description/topics after the GovernLoop slug rename

## 4. Open-source community files

- [x] Apache-2.0 `LICENSE`
- [x] `CONTRIBUTING.md`
- [x] `SECURITY.md`
- [x] `CODE_OF_CONDUCT.md`
- [x] `CHANGELOG.md`
- [x] detailed `docs/QUICKSTART.md`
- [x] naming migration guide

## 5. Reproducibility

- [x] production CLI entrypoint documented
- [x] first-run reviewer setup documented
- [x] required scope-authority environment documented
- [x] GitHub CLI dependency documented
- [x] Linear token dependency documented
- [x] environment-specific LoopX / Neutral Relay dependencies disclosed
- [ ] run documented GovernLoop quick-start commands in a clean checkout
- [ ] verify no README command depends on an uncommitted local file

## 6. Test and review gate

AGE-40 is the final pre-release implementation/rebrand PR.

- [ ] full CI passes on exact current AGE-40 HEAD
- [ ] canonical GovernLoop facade tests pass
- [ ] pre-v0.1 runtime/relay regression tests remain green
- [ ] independent reviewer reviews the actual AGE-40 PR HEAD
- [ ] all P0/P1 review findings resolved on a new exact HEAD
- [ ] final exact HEAD receives PASS

## 7. Real-world pilot evidence

AGE-37 remains the preferred final cross-project pilot evidence:

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

v0.1.0 may proceed without claiming this pilot is complete if it remains unavailable; README and application must continue to describe cross-project validation as pending.

## 8. Release lifecycle gate

After AGE-40 receives final exact-HEAD PASS and is merged under separate Product Owner authorization:

- [ ] re-read canonical `main`
- [ ] complete GitHub repository rename to `GovernLoop`
- [ ] run post-merge/post-rename smoke checks
- [ ] Product Owner explicitly authorizes `v0.1.0` tag/release
- [ ] create `v0.1.0` tag and GitHub release
- [ ] publish release notes from `CHANGELOG.md`

No automatic deploy is part of v0.1.0.

## 9. Codex for Open Source application

- [x] official application fields reviewed
- [x] repository is public
- [x] applicant is primary maintainer
- [x] ecosystem-value answer drafted without fabricated adoption metrics
- [x] API-credit use answer drafted
- [x] additional-context answer drafted
- [x] application draft updated to GovernLoop branding
- [ ] verify GitHub profile presentation is public/complete
- [ ] verify final public repository URL after rename
- [ ] fill ChatGPT-account email
- [ ] fill OpenAI Organization ID
- [ ] submit application form
- [ ] record submission date/reference if provided

Application worksheet:

`docs/CODEX_FOR_OSS_APPLICATION.md`

## 10. Maintenance mode

After v0.1.0:

- [ ] move non-release-critical enhancements to roadmap/backlog
- [ ] keep security/correctness fixes active
- [ ] avoid new governance layers without demonstrated need
- [ ] collect real external usage/adoption evidence before maturity claims
- [ ] remove pre-v0.1 naming compatibility only through an explicit breaking-change plan
