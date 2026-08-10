"""Canonical GovernLoop facade over the tested pre-release runtime core."""

from ._compat import apply_env_aliases
from agentops_runtime import runtime_loop as _legacy


def decide(task_id: str, repo: str, pr: str) -> dict:
    apply_env_aliases()
    return _legacy.decide(task_id, repo, pr)


def builder_handoff(*args, **kwargs):
    apply_env_aliases()
    return _legacy.builder_handoff(*args, **kwargs)


def _bridge_dir() -> str:
    return _legacy._bridge_dir()
