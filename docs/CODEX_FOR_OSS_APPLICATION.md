# Codex for Open Source — Application Draft

Verified against the official OpenAI application form on **2026-08-10**:

https://openai.com/form/codex-for-oss/

This file is an application worksheet, not a claim of acceptance or sponsorship.

## Current official program facts

The official form states that maintainers of active open-source projects can apply. OpenAI evaluates signals such as repository usage, ecosystem importance, and active maintenance. Applications are reviewed on a rolling basis.

Selected maintainers may receive:

- six months of ChatGPT Pro including Codex
- conditional access to Codex Security
- API credits for coding, maintainer automation, release workflows, and other core OSS work

AgentOps should apply honestly as an **early-stage project with clear ecosystem relevance**, not as a widely adopted project.

## Applicant fields

### First name

`Damon`

Source: current public GitHub profile name is `Damon Liang`.

### Last name

`Liang`

### Email associated with ChatGPT account

`<FILL FROM CHATGPT ACCOUNT>`

Do not substitute a GitHub email unless it is actually the email associated with the ChatGPT account used for the application.

### GitHub username

`liangzhipengdamon-maker`

### GitHub repository URL

`https://github.com/liangzhipengdamon-maker/Agent-Ops`

Repository visibility: public.

### Maintainer role

Select: **Primary maintainer**

Suggested supporting statement if a free-text explanation is requested:

> I am the project owner and primary maintainer. I define the governance model, maintain the runtime and review contracts, triage the project roadmap, and make final lifecycle decisions for releases.

## Why does this repository qualify?

Official limit: 500 characters.

Recommended answer (391 characters):

> AgentOps is an early-stage open-source control plane for governed coding-agent maintenance. It keeps Builder→PR→independent-review→fix loops running while preserving human authority for merge/deploy. Its deterministic scope firewall blocks repo/branch/path/operation drift and stale-head review. It addresses a growing OSS need: using autonomous coding agents safely in maintainer workflows.

Why this answer:

- it does not invent stars, downloads, or users
- it identifies ecosystem importance rather than claiming broad adoption
- it directly maps to coding-agent maintainer workflows
- it names the safety/governance contribution

## I am interested in

Recommended selections:

- **Codex Security**
- **API credits for my project**

Rationale: AgentOps handles authorization/scope boundaries and exact-HEAD review, so security analysis is directly relevant. API credits map naturally to independent PR review and maintainer automation.

## OpenAI Organization ID

`<FILL FROM OPENAI ACCOUNT>`

This is required by the current form and cannot be inferred safely from the repository or GitHub profile.

## How will you use API credits for your project?

Official limit: 500 characters.

Recommended answer (308 characters):

> Use credits for exact-HEAD independent PR review, issue triage, regression-test generation, release automation, and controlled multi-agent maintenance pilots across OSS repositories. Credits would fund reproducible CI-backed maintainer automation and security/governance testing, not production user traffic.

## Anything else we should know?

Official limit: 500 characters.

Recommended answer (350 characters):

> AgentOps was developed using the workflow it governs: repeated exact-HEAD reviews produced CHANGES_REQUESTED→automatic fixes→new HEAD→PASS while merge remained human-authorized. We are preparing v0.1.0 under Apache-2.0 and documenting limitations openly. Adoption is early; this application is based on ecosystem relevance, not inflated usage claims.

## Evidence to have visible before submission

Prefer to submit only after the v0.1.0 readiness PR is merged and the public repository visibly contains:

- strong README and quick start
- Apache-2.0 license
- contribution/security/community files
- changelog and v0.1.0 release notes/checklist
- green CI on the release-readiness HEAD
- exact-HEAD independent review evidence
- clean open-PR state or clearly intentional active PRs

Helpful additional evidence if AGE-37 finishes before submission:

- real cross-project pilot against LearnMind-English
- explicit repository/branch/baseline/path/operation authority
- automatic review/fix/re-review loop
- PASS reaching MANUAL `WAITING_PO_AUTH`
- no lifecycle authority bypass

Do not delay indefinitely for adoption metrics that do not yet exist; the official program explicitly allows projects to explain ecosystem importance even when they do not fit typical usage criteria neatly.

## Final human-only submission items

The maintainer must verify or enter:

1. ChatGPT-account email
2. OpenAI Organization ID
3. any required program terms/consent checkbox
4. final Submit action

The application should not be submitted with guessed account identifiers.
