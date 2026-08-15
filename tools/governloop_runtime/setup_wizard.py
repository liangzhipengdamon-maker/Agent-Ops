"""GovernLoop first-run reviewer binding setup.

The hardened setup implementation was developed before the public GovernLoop
name was frozen. This canonical wrapper supplies GovernLoop paths/branding,
keeps the reviewed localhost-only binding server, and owns first-run startup
of the dedicated browser runtime so coding agents do not invent CDP setup.
"""

import json
import os
import shutil
import subprocess
import time
import urllib.request
import webbrowser

from agentops_runtime import setup_wizard as _legacy
from ._compat import (BROWSER_PROFILE, CONFIG_FILE, RUNTIME_MARKER,
                      RUNTIME_NAME)

DEFAULT_CONFIG_PATH = CONFIG_FILE
DEFAULT_BROWSER_PROFILE = BROWSER_PROFILE
DEFAULT_CDP_PORT = _legacy.DEFAULT_CDP_PORT
MAX_FORM_BYTES = _legacy.MAX_FORM_BYTES
SetupError = _legacy.SetupError
BROWSER_STARTUP_TIMEOUT_SECONDS = 6.0

normalize_repository = _legacy.normalize_repository
normalize_conversation_url = _legacy.normalize_conversation_url
conversation_id_from_url = _legacy.conversation_id_from_url
normalize_cdp_port = _legacy.normalize_cdp_port
normalize_profile_path = _legacy.normalize_profile_path
normalize_config_path = _legacy.normalize_config_path
evaluate_targets = _legacy.evaluate_targets
test_connection = _legacy.test_connection
generated_config_contains_secret_fields = _legacy.generated_config_contains_secret_fields

_ORIGINAL_RENDER_PAGE = _legacy._render_page


def _render_page(values, csrf_token, config_path, status="", error=""):
    """Render the reviewed wizard with GovernLoop-owned first-run guidance."""
    repo = (values.get("repository") or "<owner/repo>").strip() or "<owner/repo>"
    if error.startswith("CDP_UNREACHABLE") or error.startswith("CDP_INVALID_RESPONSE"):
        error = (
            f"{error}. NEXT: close the dedicated GovernLoop Chrome window and rerun "
            f"`governloop setup --repo {repo}`. Do not invent a different CDP port, "
            "browser profile, or manual relay path unless setup itself reports that blocker."
        )
    page = _ORIGINAL_RENDER_PAGE(values, csrf_token, config_path,
                                 status=status, error=error)
    page = (page.replace("AgentOps", "GovernLoop")
                .replace(".agentops", ".governloop"))
    old = (
        "Open a dedicated ChatGPT conversation in the GovernLoop Chrome window, "
        "copy its <code>https://chatgpt.com/c/...</code> URL, and bind it below."
    )
    new = (
        "GovernLoop started or reused its dedicated Chrome runtime. In that GovernLoop "
        "Chrome window, sign in to ChatGPT if needed, open the reviewer conversation, "
        "copy its <code>https://chatgpt.com/c/...</code> URL, then use Test Connection "
        "and Bind Conversation below. Leave the CDP port and browser profile unchanged "
        "unless GovernLoop itself reports a blocker."
    )
    return page.replace(old, new)


def _configure_legacy_module():
    _legacy.DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_PATH
    _legacy.DEFAULT_BROWSER_PROFILE = DEFAULT_BROWSER_PROFILE
    _legacy.RUNTIME_NAME = RUNTIME_NAME
    _legacy.RUNTIME_MARKER = RUNTIME_MARKER
    _legacy.ensure_runtime_marker = ensure_runtime_marker
    _legacy._render_page = _render_page


def load_config(config_path=DEFAULT_CONFIG_PATH):
    return _legacy.load_config(config_path)


def prepare_config(existing, repository, conversation_url, cdp_port,
                   browser_profile=DEFAULT_BROWSER_PROFILE):
    _configure_legacy_module()
    return _legacy.prepare_config(existing, repository, conversation_url,
                                  cdp_port, browser_profile)


def atomic_write_config(config, config_path=DEFAULT_CONFIG_PATH):
    return _legacy.atomic_write_config(config, config_path)


def ensure_runtime_marker(browser_profile, marker=RUNTIME_MARKER):
    """Write the canonical marker plus one pre-release compatibility marker."""
    profile = normalize_profile_path(browser_profile)
    marker_value = str(marker or "").strip()
    if not marker_value:
        raise SetupError("runtime marker must not be empty")
    os.makedirs(profile, mode=0o700, exist_ok=True)
    canonical = _legacy._atomic_write_text(
        os.path.join(profile, "GOVERNLOOP_MARKER"), marker_value + "\n")
    # Neutral Relay v0.1 retains the old marker filename as a wire/runtime
    # compatibility detail. Both files carry the same GovernLoop marker value.
    _legacy._atomic_write_text(
        os.path.join(profile, "AGENTOPS_MARKER"), marker_value + "\n")
    return canonical


def _runtime_marker_matches(browser_profile, marker=RUNTIME_MARKER):
    """Match the same marker contract Neutral Relay later verifies."""
    profile = normalize_profile_path(browser_profile)
    expected = str(marker or "").strip()
    if not expected:
        return False
    for filename in ("GOVERNLOOP_MARKER", "AGENTOPS_MARKER"):
        path = os.path.join(profile, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                if handle.read().strip() != expected:
                    return False
        except OSError:
            return False
    return True


def save_binding(config_path, repository, conversation_url, cdp_port,
                 browser_profile):
    _configure_legacy_module()
    return _legacy.save_binding(config_path, repository, conversation_url,
                                cdp_port, browser_profile)


def initial_values(config_path=DEFAULT_CONFIG_PATH, repository=None,
                   cdp_port=None, browser_profile=None):
    _configure_legacy_module()
    # Pass None through so the reviewed legacy helper can prefer an existing
    # runtime.browser_profile before falling back to the canonical default.
    return _legacy.initial_values(
        config_path, repository=repository, cdp_port=cdp_port,
        browser_profile=browser_profile)


def create_setup_server(config_path=DEFAULT_CONFIG_PATH, repository=None,
                        cdp_port=None, browser_profile=None, setup_port=0,
                        connection_tester=None):
    _configure_legacy_module()
    return _legacy.create_setup_server(
        config_path=config_path,
        repository=repository,
        cdp_port=cdp_port,
        browser_profile=browser_profile,
        setup_port=setup_port,
        connection_tester=connection_tester,
    )


def _cdp_reachable(cdp_port, opener=None):
    """Return True only when the configured local CDP endpoint is live."""
    port = normalize_cdp_port(cdp_port)
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            data = json.loads(response.read().decode("utf-8"))
        return isinstance(data, dict) and bool(data.get("webSocketDebuggerUrl"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _browser_candidates():
    """Return common local Chrome/Chromium candidates without disk scanning."""
    raw = []
    explicit = os.environ.get("GOVERNLOOP_BROWSER_BIN", "").strip()
    if explicit:
        raw.append(os.path.abspath(os.path.expanduser(explicit)))

    raw.extend([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ])

    for root_var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(root_var, "").strip()
        if root:
            raw.extend([
                os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(root, "Chromium", "Application", "chrome.exe"),
            ])

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        resolved = shutil.which(name)
        if resolved:
            raw.append(resolved)

    result = []
    seen = set()
    for item in raw:
        if item and item not in seen and os.path.isfile(item):
            seen.add(item)
            result.append(item)
    return result


def ensure_browser_runtime(cdp_port, browser_profile, *, popen=None,
                           sleep=None, timeout=BROWSER_STARTUP_TIMEOUT_SECONDS):
    """Reuse or start the dedicated GovernLoop Chrome runtime.

    This is setup UX, not an authority channel. It never grants task scope or
    lifecycle permission. A live CDP port is reused only when the configured
    GovernLoop profile already carries the runtime marker Neutral Relay trusts;
    an unrelated process on the port fails closed.
    """
    port = normalize_cdp_port(cdp_port)
    profile = normalize_profile_path(browser_profile)
    if _cdp_reachable(port):
        if not _runtime_marker_matches(profile):
            return {
                "ok": False,
                "status": "BROWSER_RUNTIME_BLOCKED",
                "code": "CDP_PORT_IN_USE",
                "detail": (
                    f"CDP port {port} is reachable but the configured GovernLoop browser "
                    "profile does not match the GovernLoop runtime marker"
                ),
                "next_required_action": (
                    f"close the unrelated process using CDP port {port}, then rerun the "
                    "same `governloop setup --repo ...` command"
                ),
            }
        return {"ok": True, "status": "BROWSER_REUSED", "cdp_port": port,
                "browser_profile": profile}

    candidates = _browser_candidates()
    if not candidates:
        return {
            "ok": False,
            "status": "BROWSER_RUNTIME_BLOCKED",
            "code": "CHROME_NOT_FOUND",
            "detail": "GovernLoop could not find Google Chrome or Chromium locally",
            "next_required_action": (
                "install Google Chrome/Chromium, or set GOVERNLOOP_BROWSER_BIN to the "
                "browser executable, then rerun the same `governloop setup --repo ...` command"
            ),
        }

    browser = candidates[0]
    ensure_runtime_marker(profile)
    command = [
        browser,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://chatgpt.com/",
    ]
    launch = popen or subprocess.Popen
    snooze = sleep or time.sleep
    try:
        launch(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               start_new_session=True)
    except OSError as exc:
        return {
            "ok": False,
            "status": "BROWSER_RUNTIME_BLOCKED",
            "code": "CHROME_START_FAILED",
            "detail": f"GovernLoop could not start its dedicated browser runtime: {exc}",
            "next_required_action": (
                "fix the reported local browser launch error, then rerun the same "
                "`governloop setup --repo ...` command; do not choose a new port/profile"
            ),
        }

    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() <= deadline:
        if _cdp_reachable(port):
            return {"ok": True, "status": "BROWSER_STARTED", "cdp_port": port,
                    "browser_profile": profile, "browser": browser}
        snooze(0.25)

    return {
        "ok": False,
        "status": "BROWSER_RUNTIME_BLOCKED",
        "code": "CDP_START_TIMEOUT",
        "detail": (
            f"GovernLoop started {browser!r} but CDP port {port} did not become reachable"
        ),
        "next_required_action": (
            "close the dedicated GovernLoop Chrome window, then rerun the same "
            "`governloop setup --repo ...` command; do not invent a different port/profile"
        ),
    }


def run_setup(config_path=DEFAULT_CONFIG_PATH, repository=None, cdp_port=None,
              browser_profile=None, setup_port=0, no_open=False):
    """Start/reuse the dedicated browser, then run the existing binding wizard."""
    values = initial_values(
        config_path, repository=repository, cdp_port=cdp_port,
        browser_profile=browser_profile)
    runtime = ensure_browser_runtime(values["cdp_port"], values["browser_profile"])
    print(f"BROWSER_RUNTIME: {runtime.get('status')}")
    if not runtime.get("ok"):
        print(f"SETUP_BLOCKER: {runtime.get('code')}: {runtime.get('detail')}")
        print(f"NEXT_REQUIRED_ACTION: {runtime.get('next_required_action')}")
        return 2

    server, state, url = create_setup_server(
        config_path=config_path, repository=repository,
        cdp_port=values["cdp_port"], browser_profile=values["browser_profile"],
        setup_port=setup_port)
    print("SETUP_BIND_HOST: 127.0.0.1")
    print(f"SETUP_URL: {url}")
    print(f"CONFIG_PATH: {normalize_config_path(config_path)}")
    print("NEXT_REQUIRED_ACTION: use the setup wizard; in the dedicated GovernLoop Chrome window, sign in/open the exact ChatGPT reviewer conversation, paste its URL, Test Connection, then Bind Conversation.")
    if not no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("SETUP_CANCELLED")
    finally:
        server.server_close()
    if state.get("saved"):
        print("SETUP_SAVED: true")
        return 0
    print("SETUP_SAVED: false")
    return 1
