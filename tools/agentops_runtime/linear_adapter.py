#!/usr/bin/env python3
"""Thin read-only Linear adapter (real GraphQL).

Reads the ACTIVE Linear issue directly, including execution mode
(AUTO|MANUAL) and acceptance criteria. It is read-only and never writes,
never fabricates.

Auth: LINEAR_ACCESS_TOKEN in the environment (raw token as Authorization,
no Bearer prefix). If unavailable or the query fails, returns None so
callers surface a decision request rather than guessing.
"""

import json
import os
import urllib.request
from typing import Optional

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
TOKEN_ENV = "LINEAR_ACCESS_TOKEN"

_TEAM_KEYS = {
    "AGE": "90e043f3-2673-46f6-af69-ac7b5ea5fbb0",
    "LEA": "08a3f575-68cb-4fc3-a496-12c5931e4227",
    "DAM": "4dd0dcfc-58c0-4bd6-81df-812ba6e8e830",
}


def _token() -> Optional[str]:
    tok = os.environ.get(TOKEN_ENV, "").strip()
    return tok or None


def _team_key(identifier: str) -> Optional[str]:
    if "-" not in identifier:
        return None
    key = identifier.split("-", 1)[0]
    return key if key in _TEAM_KEYS else None


def _graphql(query: str) -> Optional[dict]:
    token = _token()
    if not token:
        return None
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_GRAPHQL_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def read_linear_issue(identifier: str) -> Optional[dict]:
    """Read one Linear issue's real state.

    Returns {identifier, title, description, state_name, state_type,
    updated_at} or None if unavailable. Never fabricates.
    """
    key = _team_key(identifier)
    if not key:
        return None
    team_id = _TEAM_KEYS[key]
    query = (
        'query { team(id: "%s") { issues(first: 100) { nodes { '
        "identifier title description updatedAt state { name type } "
        "} } } }" % team_id
    )
    data = _graphql(query)
    if not data:
        return None
    nodes = ((data.get("data") or {}).get("team") or {}).get(
        "issues", {}).get("nodes", [])
    for issue in nodes:
        if issue.get("identifier") == identifier:
            state = issue.get("state") or {}
            return {
                "identifier": issue.get("identifier"),
                "title": issue.get("title"),
                "description": issue.get("description") or "",
                "updated_at": issue.get("updatedAt"),
                "state_name": state.get("name"),
                "state_type": state.get("type"),
            }
    return None


def linear_available() -> bool:
    return _token() is not None
