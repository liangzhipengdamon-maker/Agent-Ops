#!/usr/bin/env bash
# AgentOps Neutral Relay - dedicated browser bootstrap.
#
# Ensures the AgentOps Neutral Relay has its own isolated Chrome runtime:
#   - dedicated user-data-dir (separated from LearnMind's chrome-test-profile)
#   - dedicated CDP port (9233)
#   - canonical reviewer conversation auto-opened if missing
#
# Does NOT:
# - touch LearnMind's 9223 Chrome
# - bring any tab to front in OS
# - navigate to the OLD conversation
#
# This script is the only canonical launcher for AgentOps Neutral Relay's
# browser. LearnMind legacy launchers (LearnMind-English/.claude/launch.json)
# must not be used from AgentOps runtime.
#
# Usage:
#   bash tools/neutral-relay/bootstrap_agentops_chrome.sh
#
# Or via ~/.agentops/relay/bootstrap_agentops_chrome.sh (canonical install path).
set -euo pipefail

AGENTOPS_PORT="${AGENTOPS_CDP_PORT:-9233}"
AGENTOPS_PROFILE="${AGENTOPS_CHROME_PROFILE:-$HOME/.agentops/chrome-profile}"
AGENTOPS_CONVERSATION="${AGENTOPS_CANONICAL_CONVERSATION:-https://chatgpt.com/c/6a74f5c0-a240-83ec-9cff-198ffab1140e}"
AGENTOPS_MARKER_VALUE="${AGENTOPS_MARKER:-AgentOps-9233}"
CHROME_BIN="${AGENTOPS_CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

CONVERSATION_ID=$(printf '%s' "$AGENTOPS_CONVERSATION" | sed -nE 's@.*/c/([0-9a-fA-F-]{8,}).*@\1@p')
CONVERSATION_ID=$(printf '%s' "$CONVERSATION_ID" | tr '[:upper:]' '[:lower:]')

mkdir -p "$AGENTOPS_PROFILE"

# Write the runtime marker file. Neutral Relay reads this file to verify
# the CDP endpoint actually serves the AgentOps runtime (not LearnMind).
printf '%s\n' "$AGENTOPS_MARKER_VALUE" > "${AGENTOPS_PROFILE}/AGENTOPS_MARKER"
printf '%s\n' "$CONVERSATION_ID"     > "${AGENTOPS_PROFILE}/AGENTOPS_CONVERSATION_ID"

if ! command -v lsof >/dev/null 2>&1; then
    echo "ERROR: lsof required" >&2
    exit 1
fi

if lsof -iTCP:"${AGENTOPS_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "AgentOps Chrome already listening on port ${AGENTOPS_PORT} (profile: ${AGENTOPS_PROFILE})"
    # Refresh marker files even if Chrome is already running (idempotent).
    printf '%s\n' "$AGENTOPS_MARKER_VALUE" > "${AGENTOPS_PROFILE}/AGENTOPS_MARKER"
    printf '%s\n' "$CONVERSATION_ID"     > "${AGENTOPS_PROFILE}/AGENTOPS_CONVERSATION_ID"
    exit 0
fi

if [[ ! -x "$CHROME_BIN" ]]; then
    echo "ERROR: Chrome binary not found at $CHROME_BIN" >&2
    echo "Set AGENTOPS_CHROME_BIN env var to the correct path" >&2
    exit 1
fi

echo "Launching AgentOps Chrome:"
echo "  profile:  ${AGENTOPS_PROFILE}"
echo "  port:     ${AGENTOPS_PORT}"
echo "  conv id:  ${CONVERSATION_ID}"
echo "  url:      ${AGENTOPS_CONVERSATION}"

nohup "$CHROME_BIN" \
    --user-data-dir="$AGENTOPS_PROFILE" \
    --remote-debugging-port="$AGENTOPS_PORT" \
    --remote-allow-origins='*' \
    --no-first-run \
    --no-default-browser-check \
    --new-window \
    "$AGENTOPS_CONVERSATION" \
    > "${AGENTOPS_PROFILE}/agentops-chrome.log" 2>&1 &

CHROME_PID=$!
echo "launched pid ${CHROME_PID}"

for i in $(seq 1 30); do
    if curl -s --max-time 2 "http://127.0.0.1:${AGENTOPS_PORT}/json/version" >/dev/null 2>&1; then
        echo "AgentOps Chrome is listening on ${AGENTOPS_PORT}"
        exit 0
    fi
    sleep 1
done

echo "ERROR: AgentOps Chrome did not start listening on ${AGENTOPS_PORT} within 30s" >&2
exit 1