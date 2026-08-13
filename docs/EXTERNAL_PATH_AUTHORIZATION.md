# Explicit External-Path Authorization

GovernLoop remains repository-first. This feature is a narrow exception for a controlled task that must access one exact directory outside the governed repository; it is **not** generic filesystem IAM or workspace management.

## Runtime gate

Repository authority keeps its existing repo-relative path rules. Absolute paths are still rejected by the repository Scope & Action Firewall.

For a repo-external operation, use a separately signed `governloop-external-path-authority-v1` document under the protected operator channel and verify it with:

```bash
governloop external-path-check \
  --task-id AWG-EXAMPLE \
  --operation preserve-copy \
  --target /exact/authorized/root/evidence.txt
```

The external authority binds an exact `task_id`, Standard-Mode OS `subject_id`, existing canonical `allowed_root`, explicit `allowed_operations`, `authority_id`, issuer key identity, issue time, and expiry. Verification fails closed on missing or invalid signature, wrong task/subject, expiry, protected revocation state, traversal, sibling escape, symlink escape, unsupported operation, or target escape.

Supported v1 external operations are intentionally narrow: `read`, `create`, `edit`, `copy`, `preserve-copy`, and `move`. External-path authority never grants Ready, Merge, Deploy, Release, or any other lifecycle action.

## Operator provisioning

`governloop-operator` intentionally does **not** read a signing private key. A signer outside the Builder/runtime episode must first create the signed authority or lifecycle document. The operator provisioning identity then installs it into the runtime user's fixed protected control root:

```bash
governloop-operator authorize \
  --runtime-user <builder-user> \
  --kind external_path \
  --signed-document /operator-owned/path/external-authority.json
```

Repository authority can be provisioned the same way with `--kind repository`. Exact signed lifecycle decisions are installed with `governloop-operator approve`.

The operator OS identity must differ from the Builder/runtime uid and must own the protected control root. Same-uid convention is not an authority boundary. If the required OS separation is absent, provisioning blocks rather than weakening the runtime verifier.

`governloop-operator inspect` is read-only. In this narrow revision, protected local revocation is implemented only for external-path authority:

```bash
governloop-operator revoke \
  --runtime-user <builder-user> \
  --kind external_path \
  --authority-id <authority-id>
```

The external-path verifier consumes that state fail-closed. Legacy repository-authority revocation is not claimed by this change.

## Non-goals

This feature does not add arbitrary resources, cloud/database authorization, a generic policy engine, a generic PDP/PEP protocol, multi-resource transactions, or AWG-specific hardcoded paths. AWG is the first real acceptance case; the mechanism is project-agnostic.
