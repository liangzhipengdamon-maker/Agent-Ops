# Codex for Open Source — Application Draft

Verified against the official OpenAI application form on **2026-08-10**:

https://openai.com/form/codex-for-oss/

This file is an application worksheet, not a claim of acceptance or sponsorship.

## Current official program facts

The official form states that maintainers of active open-source projects can apply. OpenAI evaluates signals such as repository usage, ecosystem importance, and active maintenance. Applications are reviewed on a rolling basis.

Selected maintainers may receive six months of ChatGPT Pro including Codex, conditional access to Codex Security, and API credits for coding, maintainer automation, release workflows, and other core OSS work.

GovernLoop should apply honestly as an **early-stage project with clear ecosystem relevance**, not as a widely adopted project.

## Applicant fields

### First name

`Damon`

### Last name

`Liang`

### Email associated with ChatGPT account

`<FILL FROM CHATGPT ACCOUNT>`

Do not substitute a GitHub email unless it is actually the email associated with the ChatGPT account used for the application.

### GitHub username

`liangzhipengdamon-maker`

### GitHub repository URL

`https://github.com/liangzhipengdamon-maker/GovernLoop`

Verify this URL after the repository slug rename. Repository visibility must remain public.

### Maintainer role

Select: **Primary maintainer**

Suggested supporting statement if requested:

> I am the project owner and primary maintainer. I define the governance model, maintain the runtime and review contracts, triage the roadmap, and make final lifecycle decisions for releases.

## Why does this repository qualify?

Official limit: 500 characters.

Recommended answer:

> GovernLoop is an early-stage open-source control plane for governed coding-agent maintenance. It keeps Builder→PR→independent-review→fix loops running while preserving explicit lifecycle authority. Its deterministic scope firewall blocks repo/branch/path/operation drift and stale-head review. It addresses a growing OSS need: using autonomous coding agents safely in maintainer workflows.

This answer deliberately does not invent stars, downloads, users, or adoption metrics. It argues ecosystem relevance and names the safety/governance contribution.

## I am interested in

Recommended selections:

- **Codex Security**
- **API credits for my project**

Rationale: GovernLoop handles authorization/scope boundaries and exact-HEAD review, so security analysis is directly relevant. API credits map naturally to independent PR review and maintainer automation.

## OpenAI Organization ID

`<FILL FROM OPENAI ACCOUNT>`

This cannot be inferred safely from the repository or GitHub profile.

## How will you use API credits for your project?

Official limit: 500 characters.

Recommended answer:

> Use credits for exact-HEAD independent PR review, issue triage, regression-test generation, release automation, and controlled multi-agent maintenance pilots across OSS repositories. Credits would fund reproducible CI-backed maintainer automation and security/governance testing, not production user traffic.

## Anything else we should know?

Official limit: 500 characters.

Recommended answer:

> GovernLoop was developed using the workflow it governs: repeated exact-HEAD reviews produced CHANGES_REQUESTED→automatic fixes→new HEAD→PASS while merge remained human-authorized. We are preparing v0.1.0 under Apache-2.0 and document limitations openly. Adoption is early; this application is based on ecosystem relevance, not inflated usage claims.

## Evidence to have visible before submission

Prefer to submit only after the GovernLoop v0.1.0 readiness/rebrand work is merged and the public repository visibly contains:

- strong README and Quick Start
- Apache-2.0 license
- contribution/security/community files
- changelog and v0.1.0 release checklist
- first-run reviewer binding
- green CI on exact release HEAD
- exact-HEAD independent review evidence
- final GovernLoop repository name/URL
- clean open-PR state or clearly intentional active PRs

Helpful additional evidence if the cross-project pilot finishes before submission:

- real pilot against LearnMind-English
- explicit repository/branch/baseline/path/operation authority
- automatic review/fix/re-review loop
- PASS reaching MANUAL `WAITING_PO_AUTH`
- no lifecycle authority bypass

Do not delay indefinitely for adoption metrics that do not yet exist; the application should remain truthful about the project's early stage.

## Final human-only submission items

The maintainer must verify or enter:

1. ChatGPT-account email
2. OpenAI Organization ID
3. any required program terms/consent checkbox
4. final Submit action

Do not submit with guessed account identifiers.
