#!/usr/bin/env python3
"""First-run browser setup for binding a ChatGPT reviewer conversation.

This is a thin configuration layer in front of the existing Neutral Relay.
It never handles ChatGPT credentials and never weakens exact-conversation
identity binding.
"""

import copy
import html
import json
import os
import re
import secrets
import tempfile
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DEFAULT_CONFIG_PATH = os.path.expanduser("~/.agentops/relay/config.json")
DEFAULT_BROWSER_PROFILE = os.path.expanduser("~/.agentops/chrome-profile")
DEFAULT_CDP_PORT = 9233
RUNTIME_NAME = "AgentOps"
RUNTIME_MARKER = "agentops-runtime-v1"
MAX_FORM_BYTES = 65536

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_CONVERSATION_PATH_RE = re.compile(r"^/c/([0-9a-fA-F-]{8,})/?$")
_SECRET_WORDS = ("password", "cookie", "token", "secret", "api_key", "apikey")


class SetupError(ValueError):
    """Invalid or unsafe setup input."""


def normalize_repository(repository):
    value = (repository or "").strip()
    if not _REPO_RE.fullmatch(value):
        raise SetupError("repository must be in owner/repo form")
    return value


def normalize_conversation_url(url):
    """Return canonical https://chatgpt.com/c/<id> or fail closed."""
    raw = (url or "").strip()
    if not raw:
        raise SetupError("ChatGPT conversation URL is required")
    try:
        parsed = urllib.parse.urlparse(raw)
        parsed_port = parsed.port  # Access can itself raise ValueError.
    except ValueError as exc:
        raise SetupError(f"invalid ChatGPT conversation URL: {exc}") from exc
    if parsed.scheme.lower() != "https":
        raise SetupError("ChatGPT conversation URL must use https")
    if parsed.username or parsed.password or parsed_port:
        raise SetupError("ChatGPT conversation URL must not contain credentials or a port")
    host = (parsed.hostname or "").lower()
    if host not in ("chatgpt.com", "www.chatgpt.com"):
        raise SetupError("URL host must be chatgpt.com")
    if parsed.query or parsed.fragment or parsed.params:
        raise SetupError("conversation URL must not contain query parameters or fragments")
    match = _CONVERSATION_PATH_RE.fullmatch(parsed.path or "")
    if not match:
        raise SetupError(
            "use a dedicated ChatGPT conversation URL: "
            "https://chatgpt.com/c/<conversation-id>")
    cid = match.group(1).lower()
    return f"https://chatgpt.com/c/{cid}"


def conversation_id_from_url(url):
    try:
        return normalize_conversation_url(url).rsplit("/", 1)[-1]
    except SetupError:
        return None


def normalize_cdp_port(port):
    try:
        value = int(port)
    except (TypeError, ValueError) as exc:
        raise SetupError("CDP port must be an integer") from exc
    if not 1 <= value <= 65535:
        raise SetupError("CDP port must be between 1 and 65535")
    return value


def normalize_profile_path(path):
    raw = (path or "").strip()
    if not raw:
        raise SetupError("browser profile path is required")
    return os.path.abspath(os.path.expanduser(raw))


def normalize_config_path(path):
    raw = (path or "").strip()
    if not raw:
        raise SetupError("config path is required")
    return os.path.abspath(os.path.expanduser(raw))


def load_config(config_path=DEFAULT_CONFIG_PATH):
    path = normalize_config_path(config_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot read existing config: {exc}") from exc
    if not isinstance(data, dict):
        raise SetupError("existing config root must be a JSON object")
    return data


def prepare_config(existing, repository, conversation_url, cdp_port,
                   browser_profile):
    """Build an updated config while preserving unrelated existing fields."""
    repository = normalize_repository(repository)
    conversation_url = normalize_conversation_url(conversation_url)
    cdp_port = normalize_cdp_port(cdp_port)
    browser_profile = normalize_profile_path(browser_profile)

    config = copy.deepcopy(existing or {})
    routes = config.get("routes", {})
    runtime = config.get("runtime", {})
    if routes is None:
        routes = {}
    if runtime is None:
        runtime = {}
    if not isinstance(routes, dict):
        raise SetupError("existing config.routes must be an object")
    if not isinstance(runtime, dict):
        raise SetupError("existing config.runtime must be an object")

    # Neutral Relay currently binds all routes to one browser runtime. Never
    # silently rewrite a pre-existing route onto a different CDP port.
    for name, route in routes.items():
        if not isinstance(route, dict):
            raise SetupError(f"existing route {name!r} must be an object")
        route_port = route.get("cdp_port")
        if route_port is not None and normalize_cdp_port(route_port) != cdp_port:
            raise SetupError(
                f"existing route {name!r} uses CDP port {route_port}; "
                "all routes in one AgentOps runtime must use the same port")

    existing_runtime_port = runtime.get("cdp_port")
    if existing_runtime_port is not None and routes:
        existing_runtime_port = normalize_cdp_port(existing_runtime_port)
        if existing_runtime_port != cdp_port:
            raise SetupError(
                f"existing runtime uses CDP port {existing_runtime_port}; "
                "choose that port or use a separate config")

    runtime_updated = copy.deepcopy(runtime)
    runtime_updated["name"] = runtime_updated.get("name") or RUNTIME_NAME
    runtime_updated["cdp_port"] = cdp_port
    runtime_updated["browser_profile"] = browser_profile
    runtime_updated["runtime_marker"] = (
        runtime_updated.get("runtime_marker") or RUNTIME_MARKER)

    route_updated = copy.deepcopy(routes.get(repository) or {})
    route_updated["conversation_url"] = conversation_url
    route_updated["cdp_port"] = cdp_port
    routes_updated = copy.deepcopy(routes)
    routes_updated[repository] = route_updated

    config["runtime"] = runtime_updated
    config["routes"] = routes_updated
    return config


def _atomic_write_text(path, text, mode=0o600):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".agentops.", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return path


def ensure_runtime_marker(browser_profile, marker=RUNTIME_MARKER):
    profile = normalize_profile_path(browser_profile)
    marker_value = str(marker or "").strip()
    if not marker_value:
        raise SetupError("runtime marker must not be empty")
    os.makedirs(profile, mode=0o700, exist_ok=True)
    return _atomic_write_text(
        os.path.join(profile, "AGENTOPS_MARKER"), marker_value + "\n")


def atomic_write_config(config, config_path=DEFAULT_CONFIG_PATH):
    path = normalize_config_path(config_path)
    payload = json.dumps(config, indent=2, sort_keys=True) + "\n"
    return _atomic_write_text(path, payload)


def save_binding(config_path, repository, conversation_url, cdp_port,
                 browser_profile):
    existing = load_config(config_path)
    updated = prepare_config(
        existing, repository, conversation_url, cdp_port, browser_profile)
    runtime = updated["runtime"]
    ensure_runtime_marker(
        runtime["browser_profile"], runtime["runtime_marker"])
    path = atomic_write_config(updated, config_path)
    return {
        "ok": True,
        "config_path": path,
        "repository": normalize_repository(repository),
        "conversation_url": normalize_conversation_url(conversation_url),
        "cdp_port": normalize_cdp_port(cdp_port),
        "browser_profile": normalize_profile_path(browser_profile),
    }


def evaluate_targets(targets, conversation_url):
    """Require exactly one open page with the configured conversation ID."""
    canonical = normalize_conversation_url(conversation_url)
    expected_id = conversation_id_from_url(canonical)
    matches = []
    for target in targets or []:
        if target.get("type") != "page":
            continue
        if conversation_id_from_url(target.get("url") or "") == expected_id:
            matches.append(target)
    if not matches:
        return {
            "ok": False,
            "code": "REVIEWER_CONVERSATION_NOT_FOUND",
            "detail": "no open ChatGPT tab matches the configured conversation",
            "matches": 0,
        }
    if len(matches) > 1:
        return {
            "ok": False,
            "code": "AMBIGUOUS_REVIEWER_CONVERSATION",
            "detail": f"{len(matches)} open tabs match; close duplicates and retry",
            "matches": len(matches),
        }
    target = matches[0]
    return {
        "ok": True,
        "code": "CONNECTED",
        "detail": "exact reviewer conversation found",
        "matches": 1,
        "target_url": target.get("url"),
        "target_id": target.get("id") or target.get("targetId"),
    }


def _read_json(url, opener=None, timeout=3):
    open_fn = opener or urllib.request.urlopen
    with open_fn(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def test_connection(conversation_url, cdp_port, opener=None):
    """Probe local Chrome CDP and exact-match the configured conversation."""
    try:
        canonical = normalize_conversation_url(conversation_url)
        port = normalize_cdp_port(cdp_port)
        version = _read_json(
            f"http://127.0.0.1:{port}/json/version", opener=opener)
        if not isinstance(version, dict) or not version.get("webSocketDebuggerUrl"):
            return {
                "ok": False,
                "code": "CDP_INVALID_RESPONSE",
                "detail": "CDP /json/version did not return webSocketDebuggerUrl",
            }
        targets = _read_json(
            f"http://127.0.0.1:{port}/json", opener=opener)
        if not isinstance(targets, list):
            return {
                "ok": False,
                "code": "CDP_INVALID_RESPONSE",
                "detail": "CDP /json did not return a target list",
            }
        result = evaluate_targets(targets, canonical)
        result["browser"] = version.get("Browser") or "unknown"
        result["cdp_port"] = port
        return result
    except (SetupError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "code": "CDP_UNREACHABLE", "detail": str(exc)}


def _contains_secret_field(value):
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(word in lowered for word in _SECRET_WORDS):
                return True
            if _contains_secret_field(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_field(item) for item in value)
    return False


def generated_config_contains_secret_fields(config):
    """Support/test helper: wizard-generated fields must never be secrets."""
    return _contains_secret_field(config)


def initial_values(config_path, repository=None, cdp_port=None,
                   browser_profile=None):
    try:
        config = load_config(config_path)
    except SetupError:
        config = {}
    routes = config.get("routes") if isinstance(config.get("routes"), dict) else {}
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    repo = (repository or "").strip()
    if not repo and len(routes) == 1:
        repo = next(iter(routes))
    route = routes.get(repo) if repo else None
    route = route if isinstance(route, dict) else {}
    return {
        "repository": repo,
        "conversation_url": route.get("conversation_url", ""),
        "cdp_port": str(cdp_port or runtime.get("cdp_port") or DEFAULT_CDP_PORT),
        "browser_profile": (
            browser_profile or runtime.get("browser_profile") or
            DEFAULT_BROWSER_PROFILE),
    }


def _render_page(values, csrf_token, config_path, status="", error=""):
    def esc(value):
        return html.escape(str(value or ""), quote=True)

    status_html = f'<div class="ok">{esc(status)}</div>' if status else ""
    error_html = f'<div class="error">{esc(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AgentOps Setup</title>
<style>
:root{{color-scheme:light dark;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
body{{margin:0;background:#111318;color:#edf1f7}}main{{max-width:720px;margin:48px auto;padding:0 20px 48px}}
.card{{background:#1b1f27;border:1px solid #303744;border-radius:16px;padding:28px;box-shadow:0 14px 40px #0005}}
h1{{margin:0 0 8px;font-size:28px}}p{{color:#b9c2d0;line-height:1.55}}label{{display:block;margin-top:18px;font-weight:650}}
input{{box-sizing:border-box;width:100%;margin-top:7px;padding:12px 13px;border-radius:9px;border:1px solid #465064;background:#101319;color:#f6f8fb;font:inherit}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.actions{{display:flex;gap:10px;margin-top:24px;flex-wrap:wrap}}
button{{border:0;border-radius:9px;padding:11px 16px;font:inherit;font-weight:700;cursor:pointer}}.primary{{background:#e8edf6;color:#101319}}.secondary{{background:#303744;color:#edf1f7}}
.note{{margin-top:20px;padding:14px;border-radius:10px;background:#141922;color:#aeb8c8;font-size:14px}}.ok{{margin:16px 0;padding:12px;border-radius:9px;background:#153821;color:#b9f2c9}}.error{{margin:16px 0;padding:12px;border-radius:9px;background:#451b20;color:#ffc5ca}}code{{color:#d7e2f5}}
@media(max-width:620px){{.row{{grid-template-columns:1fr}}}}
</style></head><body><main><div class="card">
<h1>Connect your ChatGPT reviewer</h1>
<p>Open a dedicated ChatGPT conversation in the AgentOps Chrome window, copy its <code>https://chatgpt.com/c/...</code> URL, and bind it below.</p>
{status_html}{error_html}
<form method="post"><input type="hidden" name="csrf" value="{esc(csrf_token)}">
<label>Repository<input name="repository" required placeholder="owner/repository" value="{esc(values.get('repository'))}"></label>
<label>Dedicated ChatGPT conversation URL<input name="conversation_url" required placeholder="https://chatgpt.com/c/..." value="{esc(values.get('conversation_url'))}"></label>
<div class="row"><label>AgentOps CDP port<input name="cdp_port" inputmode="numeric" required value="{esc(values.get('cdp_port'))}"></label>
<label>Browser profile<input name="browser_profile" required value="{esc(values.get('browser_profile'))}"></label></div>
<div class="actions"><button class="secondary" formaction="/test" type="submit">Test Connection</button><button class="primary" formaction="/save" type="submit">Bind Conversation</button></div></form>
<div class="note"><strong>Privacy:</strong> AgentOps never asks for or stores your ChatGPT password, cookies, OpenAI API key, or session token. You sign in directly on ChatGPT. This page stores only the exact reviewer conversation URL and local browser runtime settings.<br><br>Config: <code>{esc(normalize_config_path(config_path))}</code></div>
</div></main></body></html>"""


def _parse_form(handler):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise SetupError("invalid Content-Length") from exc
    if length <= 0 or length > MAX_FORM_BYTES:
        raise SetupError("invalid setup form size")
    raw = handler.rfile.read(length).decode("utf-8")
    fields = urllib.parse.parse_qs(raw, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in fields.items()}


def create_setup_server(config_path=DEFAULT_CONFIG_PATH, repository=None,
                        cdp_port=None, browser_profile=None, setup_port=0,
                        connection_tester=None):
    """Create a localhost-only setup server. Caller owns serve/close."""
    config_path = normalize_config_path(config_path)
    values = initial_values(config_path, repository, cdp_port, browser_profile)
    csrf_token = secrets.token_urlsafe(24)
    tester = connection_tester or test_connection
    state = {"saved": False, "last_result": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _host_is_local(self):
            host = (self.headers.get("Host") or "").split(":", 1)[0].lower()
            return host in ("127.0.0.1", "localhost")

        def _send(self, body, status_code=200):
            encoded = body.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if not self._host_is_local():
                self.send_error(421, "local Host required")
                return
            if self.path != "/":
                self.send_error(404)
                return
            self._send(_render_page(values, csrf_token, config_path))

        def do_POST(self):
            if not self._host_is_local():
                self.send_error(421, "local Host required")
                return
            if self.path not in ("/test", "/save"):
                self.send_error(404)
                return
            try:
                form = _parse_form(self)
                if not secrets.compare_digest(form.get("csrf", ""), csrf_token):
                    raise SetupError("invalid setup session token")
                submitted = {
                    "repository": form.get("repository", "").strip(),
                    "conversation_url": form.get("conversation_url", "").strip(),
                    "cdp_port": form.get("cdp_port", "").strip(),
                    "browser_profile": form.get("browser_profile", "").strip(),
                }
                normalize_repository(submitted["repository"])
                normalize_conversation_url(submitted["conversation_url"])
                normalize_cdp_port(submitted["cdp_port"])
                normalize_profile_path(submitted["browser_profile"])
                values.update(submitted)

                if self.path == "/test":
                    result = tester(
                        submitted["conversation_url"], submitted["cdp_port"])
                    state["last_result"] = result
                    if result.get("ok"):
                        message = (
                            "Connected: exactly one reviewer conversation "
                            f"found on CDP port {submitted['cdp_port']}.")
                        self._send(_render_page(
                            values, csrf_token, config_path, status=message))
                    else:
                        message = (
                            f"{result.get('code', 'CONNECTION_FAILED')}: "
                            f"{result.get('detail', 'connection test failed')}")
                        self._send(_render_page(
                            values, csrf_token, config_path, error=message))
                    return

                result = save_binding(
                    config_path, submitted["repository"],
                    submitted["conversation_url"], submitted["cdp_port"],
                    submitted["browser_profile"])
                state["saved"] = True
                state["last_result"] = result
                self._send(_render_page(
                    values, csrf_token, config_path,
                    status=("Reviewer conversation bound successfully. "
                            "You can close this tab.")))
                threading.Thread(
                    target=self.server.shutdown, daemon=True).start()
            except SetupError as exc:
                self._send(_render_page(
                    values, csrf_token, config_path, error=str(exc)), 400)
            except OSError as exc:
                self._send(_render_page(
                    values, csrf_token, config_path,
                    error=f"configuration write failed: {exc}"), 500)

    server = ThreadingHTTPServer(("127.0.0.1", int(setup_port or 0)), Handler)
    port = server.server_address[1]
    return server, state, f"http://127.0.0.1:{port}/"


def run_setup(config_path=DEFAULT_CONFIG_PATH, repository=None, cdp_port=None,
              browser_profile=None, setup_port=0, no_open=False):
    server, state, url = create_setup_server(
        config_path=config_path, repository=repository, cdp_port=cdp_port,
        browser_profile=browser_profile, setup_port=setup_port)
    print("SETUP_BIND_HOST: 127.0.0.1")
    print(f"SETUP_URL: {url}")
    print(f"CONFIG_PATH: {normalize_config_path(config_path)}")
    print("Open a dedicated ChatGPT conversation in the AgentOps Chrome window before Test Connection.")
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
