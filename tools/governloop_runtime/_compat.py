"""Pre-v0.1 compatibility bridge for the GovernLoop rename.

Public configuration is GOV​ERNLOOP_* / ~/.governloop.  The already-tested
pre-release implementation still reads a few AGENTOPS_* symbols internally;
this module maps the canonical names into that implementation at process
startup without allowing review/runtime state to create new authority.
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
RELAY_BIN = os.path.join(GOVERNLOOP_HOME, "relay", "neutral_relay.py")
CONFIG_FILE = os.path.join(GOVERNLOOP_HOME, "relay", "config.json")
BROWSER_PROFILE = os.path.join(GOVERNLOOP_HOME, "chrome-profile")
RUNTIME_NAME = "GovernLoop"
RUNTIME_MARKER = "governloop-runtime-v1"


def apply_env_aliases() -> None:
    """Map canonical GovernLoop authority env into the tested legacy reader.

    Canonical values win.  Legacy values are accepted only as a migration
    convenience and are mirrored back to the canonical name so child code has
    one visible effective value.  No defaults grant authority.
    """
    for canonical, legacy in ENV_ALIASES.items():
        canonical_value = os.environ.get(canonical, "").strip()
        legacy_value = os.environ.get(legacy, "").strip()
        if canonical_value:
            os.environ[legacy] = canonical_value
        elif legacy_value:
            os.environ[canonical] = legacy_value


def configure_legacy_relay() -> None:
    """Point the proven pre-release relay client at GovernLoop local state."""
    from agentops_runtime import relay_client

    relay_client.RELAY_BIN = RELAY_BIN
    relay_client.CONFIG_FILE = CONFIG_FILE


def configure_process() -> None:
    apply_env_aliases()
    configure_legacy_relay()
