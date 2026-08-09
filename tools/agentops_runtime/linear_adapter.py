#!/usr/bin/env python3
"""AGE-30 thin read-only Linear adapter.

Reads the REAL Linear issue state via the Linear GraphQL API using an
`LINEAR_ACCESS_TOKEN` from the environment. It is intentionally thin:
read-only, single issue query, fail-open when the token is absent.

Design rule: do NOT fabricate Linear state. If the token is unavailable
or the query fails, return None so callers treat Linear as "no new
information" rather than guessing.
"""

import json
import os
import urllib.request
from typing import Optional


LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"
TOKEN_ENV = "LINEAR_ACCESS_TOKEN"


def _token() -> Optional[str]:
    tok = os.environ.get(TOKEN_ENV, "").strip()
    return tok or None


def read_linear_issue(identifier: str) -> Optional[dict]:
    """Read one Linear issue's real state (identifier, title, state,
    updatedAt). Returns None when unavailable (no token / network / parse
    failure). Never fabricates data."""
    token = _token()
    if not token:
        return None
    query = (
        'query { issue(identifier: "%s") { '
        "identifier title updatedAt state { name type } "
        "} }" % identifier
    )
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_GRAPHQL_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    issue = (data.get("data") or {}).get("issue")
    if not issue:
        return None
    state = issue.get("state") or {}
    return {
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "updated_at": issue.get("updatedAt"),
        "state_name": state.get("name"),
        "state_type": state.get("type"),
    }


def linear_available() -> bool:
    return _token() is not None
