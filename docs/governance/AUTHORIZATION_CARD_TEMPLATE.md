# Authorization Risk Card Template

This template is used by the Agent to summarize a requested mission into a strict boundary definition. It maps directly to the underlying Mission Authorization Envelope (AGE-3).

```text
任务 (Task): [Short description of the goal]
项目 (Project): [Canonical Repository, e.g., liangzhipengdamon-maker/Agent-Ops]
风险 (Risk): [低 (Low) / 中 (Medium) / 高 (High)]
范围 (Scope): [Allowed paths, e.g., docs/governance/**]
终点 (Terminal Stage): [e.g., DRAFT_PR, LOCAL_READY]
禁止 (Prohibitions): [Explicitly blocked actions/paths, e.g., No DB migrations, No workflows]
授权码 (Auth Code): [Unique nonce/idempotency key, e.g., AUTH-8f2a9c]
卡片哈希 (Card Hash): [SHA256 of the normalized card contents, e.g., HASH-5c2b...]
```

## Field Definitions
- **风险 (Risk)**: 
  - *低 (Low)*: Documentation, local tests, no production impact.
  - *中 (Medium)*: Code changes within isolated modules, draft PR creation.
  - *高 (High)*: Core architecture, CI/CD changes, database migrations, deployments.
- **授权码 (Auth Code)**: A standard nonce/idempotency key for preventing replay.
- **卡片哈希 (Card Hash)**: A precise cryptographic binding to the proposed mission boundaries. It must be computed as the `SHA256` digest (hex encoded) of the UTF-8 normalized string of the entire card body, excluding the hash line itself. A simple nonce or auth code alone does not constitute a cryptographic binding. The Card Hash ensures the PO is approving the exact, immutable boundaries presented. If the Agent alters the card contents, a new hash must be generated, and any previous approval is invalidated.
