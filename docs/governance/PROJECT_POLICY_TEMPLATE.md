# Project Policy Template

This template defines project-level security policies. 

**CRITICAL RULE:** Project-level policies can ONLY tighten (restrict) the global Agent-Ops authorization rules. They cannot relax or bypass global safety nets (e.g., they cannot bypass exact-SHA validation for merges).

## Base Configuration

```yaml
project_id: "liangzhipengdamon-maker/Agent-Ops"
policy_version: "v1.0"

# Strict Risk Limits (Cannot exceed global maximums)
max_budget:
  max_changed_files_per_mission: 50
  max_commits_per_mission: 10
  max_cost_usd_per_mission: 2.00

# High-Risk Defaults
high_risk_actions:
  allow_database_migrations_by_default: false
  allow_workflow_mutations_by_default: false
  allow_secret_access_by_default: false

# Review and Gate Requirements
gates:
  require_human_review_for_merge: true
  require_passing_ci_for_ready: true

# Base SHA Conflict Policy
# Options: PINNED_BASE (default/strictest), REBASE_AND_REVALIDATE
default_conflict_policy: "PINNED_BASE"
```

## Enforcement
The Trusted Authorization Provider (TAP) merges this project template with the PO's instruction. If a PO's instruction attempts to exceed these limits (e.g., touching 100 files when the limit is 50), the TAP must `DENY` the generation of the envelope and request explicit `AMEND` authorization from the PO to temporarily override the project limit.
