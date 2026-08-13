# Explicit External-Path Authorization

GovernLoop remains repository-first. This change only fixes one boundary case: a controlled task may explicitly authorize one repository-external directory by placing that absolute directory in the existing signed authority `allowed_paths` list.

No new authority schema, operator CLI, revocation system, subject model, or generic resource framework is introduced.

## Behavior

Existing repository-relative paths are unchanged.

Without an explicit absolute entry, an absolute target is still blocked.

With a signed authority such as:

```json
{
  "allowed_paths": [
    "tools",
    "/Users/example/workspace/artifacts/evidence"
  ]
}
```

GovernLoop may allow that exact external directory and its canonical descendants for the already-authorized task and operations.

It still blocks sibling directories, `..` traversal, symlink escape outside the authorized root, filesystem-root (`/`) authorization, and lifecycle actions not separately authorized.

This is an explicit path exception, not generic filesystem IAM. The mechanism is project-agnostic.
