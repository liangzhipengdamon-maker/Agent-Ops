"""Pre-v0.1 compatibility bridge for the GovernLoop rename.

Public configuration is GOVERNLOOP_* / ~/.governloop. The already-tested
pre-release implementation still reads a few AGENTOPS_* symbols internally;
this module maps canonical names into that implementation at process startup.

For task execution, positive scope authority is special: raw process values
are cleared and replaced only by a verified operator authority bundle before
legacy aliases are populated. Task/prompt/Builder text therefore cannot become
positive scope authority merely by exporting GOVERNLOOP_* values.
"""

import os


ENV_ALIASES = {
    "GOVERNLOOP_SCOPE_REPOSITORY": "AGENTOPS_SCOPE_REPOSITORY",
    "GOVERNLOOP_AUTHORIZED_BRANCH": "AGENTOPS_AUTHORIZED_BRANCH",
    "GOVERNLOOP_BASELINE_SHA": "AGENTOPS_BASELINE_SHA",
    "GOVERNLOOP_AUTHORIZED_OPERATIONS": "AGENTOPS_AUTHORIZED_OPERATIONS",
    "GOVERNLOOP_ALLOWED_PATHS": "AGENTOPS_ALLOWED_PATHS",
    "GOVERNLOOP_PROTECTED_REPOSITORIES": "AGENTOPS_PROTECTED_REPOSITORIES",
    "GOVERNLOOP_ALLOW_READY_MERGE_DEPLOY": "AGENTOPS_ALLOW_READY_MERGE_DEPLOY",
    "GOVERNLOOP_TRUSTED_REVIEWERS": "AGENTOPS_TRUSTED_REVIEWERS",
}

GOVERNLOOP_HOME = os.path.expanduser("~/.governloop")
CONFIG_FILE = os.path.join(GOVERNLOOP_HOME, "relay", "config.json")
BROWSER_PROFILE = os.path.join(GOVERNLOOP_HOME, "chrome-profile")
RUNTIME_NAME = "GovernLoop"
RUNTIME_MARKER = "governloop-runtime-v1"

_TOOLS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SOURCE_RELAY_BIN = os.path.join(_TOOLS_DIR, "neutral-relay", "neutral_relay.py")
_FALLBACK_RELAY_BIN = os.path.join(GOVERNLOOP_HOME, "relay", "neutral_relay.py")


def relay_bin() -> str:
    """Resolve the relay binary for the current repository-first release."""
    explicit = os.environ.get("GOVERNLOOP_RELAY_BIN", "").strip()
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    if os.path.isfile(_SOURCE_RELAY_BIN):
        return _SOURCE_RELAY_BIN
    return _FALLBACK_RELAY_BIN


def apply_env_aliases() -> None:
    """Map canonical GovernLoop config into the tested legacy reader.

    Presence of a canonical variable wins even when its value is empty. This
    matters for revocation: an explicitly empty GOVERNLOOP_* value must not be
    repopulated from stale AGENTOPS_* process state. Legacy values are used
    only when the canonical variable is genuinely absent. No defaults grant
    authority.

    Public task execution does not call this on raw positive authority: see
    ``configure_process(task_id=...)`` below, which verifies an operator bundle
    first. The standalone function remains for pre-v0.1 compatibility tests
    and non-task setup paths.
    """
    for canonical, legacy in ENV_ALIASES.items():
        if canonical in os.environ:
            os.environ[legacy] = os.environ.get(canonical, "").strip()
        elif legacy in os.environ:
            os.environ[canonical] = os.environ.get(legacy, "").strip()


def configure_legacy_relay() -> None:
    """Point the proven pre-release relay client at GovernLoop local state."""
    from agentops_runtime import relay_client

    relay_client.RELAY_BIN = relay_bin()
    relay_client.CONFIG_FILE = CONFIG_FILE


def configure_process(task_id=None, expected_repo=None, mode="signed"):
    """Configure one canonical GovernLoop process.

    When ``task_id`` is supplied, task execution requires a verified positive
    authority source selected by ``mode``:

      * ``"signed"`` (default, unchanged) — only the externally signed
        operator authority bundle is accepted.
      * ``"interactive_local"`` — same as signed, with a fallback to the
        same-uid task-scope file ``governloop setup-task-scope`` writes.

    Raw positive scope values already present in the process are
    ignored/cleared before the compatibility aliases are populated. The
    resolved mode is also projected to ``AGENTOPS_MODE`` / ``GOVERNLOOP_MODE``
    so the fence layer (``builder_handoff`` / ``_verified_scope_policy``)
    can read it without prop-drilling. The returned status is suitable for
    a deterministic CLI preflight.
    """
    if mode not in ("signed", "interactive_local"):
        mode = "signed"
    authority_status = {"ok": True, "status": "NOT_REQUIRED"}
    if task_id:
        from .authority import apply_verified_authority
        authority_status = apply_verified_authority(
            task_id, expected_repo=expected_repo, mode=mode)
    os.environ["AGENTOPS_MODE"] = mode
    os.environ["GOVERNLOOP_MODE"] = mode
    apply_env_aliases()
    configure_legacy_relay()
    return authority_status
