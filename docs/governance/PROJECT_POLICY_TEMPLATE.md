# Project Policy Template

This template defines project-level security policies for the Agent-Ops unattended control plane. 

**CRITICAL RULE:** Organization-level un-overridable rules (like exact-SHA validation for merges) can NEVER be relaxed, even through an `AMEND` authorization. 

## Base Configuration

```yaml
project_id: "liangzhipengdamon-maker/Agent-Ops"
policy_version: "v1.1"

# Project Budgets (Can be explicitly amended by PO)
max_budget:
  max_changed_files_per_mission: 50
  max_commits_per_mission: 10
  max_cost_usd_per_mission: 2.00

# High-Risk Defaults (Organization strict, overrides possible only if explicitly stated)
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

## Enforcement and Amendments
- **Immutable Rules**: Global strict principles, such as Exact-SHA binding for Deployments and Merges, are hardcoded and non-negotiable.
- **Budget Adjustments**: Project budget defaults (e.g., `max_changed_files`) may be adjusted explicitly by the Product Owner for a specific mission using an `AMEND` authorization binding the original Auth Code and Card Hash. 
- **Amendment Scope**: An `AMEND` authorization *only* modifies the explicitly listed fields in the Amendment Card. All other fields continue to inherit the restrictions from the original pre-authorized envelope and the project defaults.
