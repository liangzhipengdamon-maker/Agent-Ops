"""GovernLoop first-run reviewer binding setup.

The hardened setup implementation was developed before the public GovernLoop
name was frozen. This canonical wrapper supplies GovernLoop paths/branding
while preserving the already-reviewed validation and localhost-only server.
"""

import json
import os
import webbrowser

from agentops_runtime import setup_wizard as _legacy
from ._compat import (BROWSER_PROFILE, CONFIG_FILE, RUNTIME_MARKER,
                      RUNTIME_NAME)

DEFAULT_CONFIG_PATH = CONFIG_FILE
DEFAULT_BROWSER_PROFILE = BROWSER_PROFILE
DEFAULT_CDP_PORT = _legacy.DEFAULT_CDP_PORT
MAX_FORM_BYTES = _legacy.MAX_FORM_BYTES
SetupError = _legacy.SetupError

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
    page = _ORIGINAL_RENDER_PAGE(values, csrf_token, config_path,
                                 status=status, error=error)
    return (page.replace("AgentOps", "GovernLoop")
                .replace(".agentops", ".governloop"))


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


def save_binding(config_path, repository, conversation_url, cdp_port,
                 browser_profile):
    _configure_legacy_module()
    return _legacy.save_binding(config_path, repository, conversation_url,
                                cdp_port, browser_profile)


def initial_values(config_path=DEFAULT_CONFIG_PATH, repository=None,
                   cdp_port=None, browser_profile=None):
    _configure_legacy_module()
    return _legacy.initial_values(
        config_path, repository=repository, cdp_port=cdp_port,
        browser_profile=browser_profile or DEFAULT_BROWSER_PROFILE)


def create_setup_server(config_path=DEFAULT_CONFIG_PATH, repository=None,
                        cdp_port=None, browser_profile=None, setup_port=0,
                        connection_tester=None):
    _configure_legacy_module()
    return _legacy.create_setup_server(
        config_path=config_path,
        repository=repository,
        cdp_port=cdp_port,
        browser_profile=browser_profile or DEFAULT_BROWSER_PROFILE,
        setup_port=setup_port,
        connection_tester=connection_tester,
    )


def run_setup(config_path=DEFAULT_CONFIG_PATH, repository=None, cdp_port=None,
              browser_profile=None, setup_port=0, no_open=False):
    server, state, url = create_setup_server(
        config_path=config_path, repository=repository, cdp_port=cdp_port,
        browser_profile=browser_profile or DEFAULT_BROWSER_PROFILE,
        setup_port=setup_port)
    print("SETUP_BIND_HOST: 127.0.0.1")
    print(f"SETUP_URL: {url}")
    print(f"CONFIG_PATH: {normalize_config_path(config_path)}")
    print("Open a dedicated ChatGPT conversation in the GovernLoop Chrome window before Test Connection.")
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
