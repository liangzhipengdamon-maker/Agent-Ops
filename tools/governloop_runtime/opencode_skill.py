"""Install/update GovernLoop's canonical OpenCode global skill."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from importlib import resources
from pathlib import Path


SKILL_RELATIVE_PATH = Path(".config/opencode/skills/governloop/SKILL.md")


def canonical_skill_text() -> str:
    return (
        resources.files("governloop_runtime")
        .joinpath("skills", "governloop", "SKILL.md")
        .read_text(encoding="utf-8")
    )


def default_target_path() -> Path:
    return Path.home() / SKILL_RELATIVE_PATH


def install(target: Path | None = None) -> dict:
    destination = Path(target) if target is not None else default_target_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = canonical_skill_text()
    fd, tmp = tempfile.mkstemp(prefix=destination.name + ".", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {
        "status": "OPENCODE_SKILL_INSTALLED",
        "skill": "governloop",
        "path": str(destination),
        "global_agents_modified": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governloop install-opencode-skill",
        description="Install/update the canonical GovernLoop OpenCode global skill.",
    )
    parser.add_argument("--target", help=argparse.SUPPRESS)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    target = Path(args.target).expanduser() if args.target else None
    try:
        result = install(target=target)
    except (OSError, FileNotFoundError) as exc:
        print(json.dumps({
            "status": "OPENCODE_SKILL_INSTALL_FAILED",
            "detail": str(exc),
        }, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
