"""Read-only local HTTP + SSE server for Cobalt Agent Desk (100% Python stdlib)."""

from __future__ import annotations

import argparse
import http.server
import json
import pathlib
import re
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from typing import Any

from cobalt_desk import APP_ID, DEFAULT_PORT, __version__
from cobalt_desk.demo_fixtures import DemoEnvironment
from cobalt_desk.git_radar import GitWorktreeRadar
from cobalt_desk.scanner import AgentScanner

THIS_DIR = pathlib.Path(__file__).resolve().parent
UI_DIR = THIS_DIR / "ui"

ALLOWED_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})

ASSET_MIME_TYPES: dict[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
}

FAVICON_SVG_BYTES: bytes = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="7" fill="#1e40af"/>'
    '<rect x="6" y="7" width="8" height="8" rx="1.5" fill="#ffffff"/>'
    '<rect x="18" y="7" width="8" height="8" rx="1.5" fill="#93c5fd"/>'
    '<rect x="6" y="18" width="8" height="7" rx="1.5" fill="#93c5fd"/>'
    '<rect x="18" y="18" width="8" height="7" rx="1.5" fill="#ffffff"/>'
    "</svg>"
).encode("utf-8")

INVALID_PATH_CHARS: frozenset[str] = frozenset('\x00\r\n"*?<>|')


def safe_resolve_under(base_dir: pathlib.Path, rel_path: str) -> pathlib.Path | None:
    """Resolve `rel_path` strictly inside `base_dir`; return None on traversal or invalid chars."""
    if not rel_path or any(ch in INVALID_PATH_CHARS for ch in rel_path):
        return None
    cleaned = rel_path.strip().replace("\\", "/")
    if cleaned.startswith("/") or ":" in cleaned:
        return None
    parts = [p for p in cleaned.split("/") if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None
    try:
        base_resolved = base_dir.resolve()
        candidate = base_resolved.joinpath(*parts).resolve()
        if candidate == base_resolved or not candidate.is_relative_to(base_resolved):
            return None
        return candidate
    except OSError:
        return None


def _strip_host_port(raw_host: str) -> str:
    h = raw_host.strip().lower()
    if not h:
        return ""
    if h.startswith("["):
        end = h.find("]")
        if end == -1:
            return ""
        rest = h[end + 1 :]
        if rest and not re.fullmatch(r":\d+", rest):
            return ""
        return h[: end + 1]
    if ":" in h:
        host_part, port_part = h.split(":", 1)
        if not port_part.isdigit():
            return ""
        return host_part
    return h


def is_allowed_origin(origin_hdr: str) -> bool:
    """Allow empty Origin (same-origin GET/SSE) or localhost origins; block 'null' & foreign origins."""
    val = origin_hdr.strip()
    if not val:
        return True
    if val.lower() == "null":
        return False
    try:
        parsed = urllib.parse.urlsplit(val)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


class DeskState:
    """Shared read-only runtime state for HTTP + SSE handlers."""

    def __init__(
        self,
        repo_dir: pathlib.Path | None = None,
        claude_projects_dir: pathlib.Path | None = None,
        antigravity_brain_dir: pathlib.Path | None = None,
        claude_agents_dir: pathlib.Path | None = None,
        claude_sessions_dir: pathlib.Path | None = None,
        demo_env: DemoEnvironment | None = None,
    ) -> None:
        self.demo_env = demo_env
        is_demo = demo_env is not None
        if demo_env is not None:
            self.scanner = AgentScanner(
                claude_projects_dir=demo_env.claude_projects_dir,
                antigravity_brain_dir=demo_env.antigravity_brain_dir,
                claude_agents_dir=demo_env.claude_agents_dir,
                claude_sessions_dir=demo_env.claude_sessions_dir,
                demo_mode=True,
                pre_scan_hook=demo_env.keep_warm,
            )
            self.git_radar = GitWorktreeRadar(static_demo_worktrees=demo_env.worktrees)
        else:
            self.scanner = AgentScanner(
                claude_projects_dir=claude_projects_dir,
                antigravity_brain_dir=antigravity_brain_dir,
                claude_agents_dir=claude_agents_dir,
                claude_sessions_dir=claude_sessions_dir,
                demo_mode=False,
            )
            self.git_radar = GitWorktreeRadar(repo_dir=repo_dir)
        self.demo_mode = is_demo


class DeskHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], state: DeskState) -> None:
        if ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(server_address, DeskRequestHandler)
        self.state = state
        self.shutdown_event = threading.Event()

    def server_close(self) -> None:
        self.shutdown_event.set()
        super().server_close()


class DeskRequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
        if len(args) >= 2 and str(args[1]).startswith(("4", "5")):
            sys.stderr.write(f"[{APP_ID}] {self.address_string()} - {fmt % args}\n")

    def _verify_security(self) -> bool:
        host_hdr = _strip_host_port(self.headers.get("Host") or "")
        if host_hdr not in ALLOWED_HOSTS:
            self._send_json(403, {"error": "Forbidden Host header (DNS rebinding guard)"})
            return False

        sfs = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if sfs and sfs not in ("same-origin", "none"):
            self._send_json(403, {"error": "Forbidden cross-site request"})
            return False

        origin = self.headers.get("Origin") or ""
        if origin and not is_allowed_origin(origin):
            self._send_json(403, {"error": "Forbidden Origin header"})
            return False

        return True

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _send_html(self, html_bytes: bytes) -> None:
        try:
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; font-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none';",
            )
            self.end_headers()
            self.wfile.write(html_bytes)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def do_GET(self) -> None:  # noqa: N802
        if not self._verify_security():
            return

        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        srv: DeskHTTPServer = self.server  # type: ignore[assignment]
        state = srv.state

        if route in ("/", "/index.html"):
            ui_file = UI_DIR / "index.html"
            if not ui_file.is_file():
                self._send_json(500, {"error": "Missing ui/index.html"})
                return
            self._send_html(ui_file.read_bytes())
            return

        if route == "/favicon.ico":
            try:
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(FAVICON_SVG_BYTES)))
                self.send_header("Connection", "close")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
                self.end_headers()
                self.wfile.write(FAVICON_SVG_BYTES)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            return

        if route.startswith("/assets/"):
            rel_asset = urllib.parse.unquote(route[len("/assets/") :])
            target = safe_resolve_under(UI_DIR, rel_asset)
            if target is None:
                self._send_json(403, {"error": "Invalid asset path"})
                return
            mime = ASSET_MIME_TYPES.get(target.suffix.lower())
            if mime is None:
                self._send_json(403, {"error": "Asset extension not allowed"})
                return
            if not target.is_file():
                self._send_json(404, {"error": "Asset not found"})
                return
            try:
                data = target.read_bytes()
                self.close_connection = True
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                cache_hdr = "public, max-age=86400" if target.suffix.lower() == ".woff2" else "no-store"
                self.send_header("Cache-Control", cache_hdr)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            return

        if route == "/api/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "app": APP_ID,
                    "version": __version__,
                    "demo": state.demo_mode,
                    "worktrees_enabled": state.git_radar.enabled,
                },
            )
            return

        if route == "/api/agents":
            scope = qs.get("scope", ["all"])[0]
            try:
                window_h = min(max(float(qs.get("window_hours", ["24"])[0]), 0.5), 336.0)
            except ValueError:
                window_h = 24.0
            self._send_json(200, state.scanner.scan(scope=scope, window_hours=window_h))
            return

        if route == "/api/agent-detail":
            agent_id = qs.get("id", [""])[0]
            code, payload = state.scanner.get_agent_detail(agent_id)
            self._send_json(code, payload)
            return

        if route == "/api/worktrees":
            force = qs.get("force", ["0"])[0] == "1"
            self._send_json(
                200,
                {
                    "enabled": state.git_radar.enabled,
                    "demo": state.demo_mode,
                    "worktrees": state.git_radar.get_worktrees(force=force),
                },
            )
            return

        if route == "/api/stream/agents":
            scope = qs.get("scope", ["all"])[0]
            try:
                window_h = min(max(float(qs.get("window_hours", ["24"])[0]), 0.5), 336.0)
            except ValueError:
                window_h = 24.0
            self._handle_sse_agents(scope, window_h, srv)
            return

        self._send_json(404, {"error": f"Unknown route: {route}"})

    def _begin_sse(self) -> bool:
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _write_sse_event(self, event: str, data: Any) -> bool:
        payload = json.dumps(data, ensure_ascii=False)
        msg = f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
        try:
            self.wfile.write(msg)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return False

    def _handle_sse_agents(self, scope: str, window_hours: float, srv: DeskHTTPServer) -> None:
        last_fp, _ = srv.state.scanner.scan_with_fingerprint(scope=scope, window_hours=window_hours)
        if not self._begin_sse():
            return

        last_ping = time.time()
        while not srv.shutdown_event.is_set():
            if srv.shutdown_event.wait(0.85):
                break
            try:
                cur_fp, snapshot = srv.state.scanner.scan_with_fingerprint(
                    scope=scope, window_hours=window_hours
                )
                if cur_fp != last_fp:
                    last_fp = cur_fp
                    if not self._write_sse_event("agents_update", snapshot):
                        break
                    last_ping = time.time()
                elif (time.time() - last_ping) >= 10.0:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_ping = time.time()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                break


def _reconfigure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cobalt-agent-desk",
        description="Cobalt Agent Desk — Zero-dependency, read-only local multi-agent monitor",
    )
    ap.add_argument(
        "--demo",
        action="store_true",
        help="Run with 100%% synthetic isolated demo sessions (never reads real home directories)",
    )
    ap.add_argument(
        "--repo",
        default="",
        help="Optional path to a local Git repository to enable the Git Worktrees Radar tab",
    )
    ap.add_argument(
        "--claude-dir",
        default="",
        help="Optional override path to `.claude` root directory (e.g. when monitoring across WSL2)",
    )
    ap.add_argument(
        "--antigravity-dir",
        default="",
        help="Optional override path to `.gemini/antigravity/brain` directory",
    )
    ap.add_argument("--host", default="127.0.0.1", help="Bind address (localhost only)")
    ap.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Preferred port number (default: {DEFAULT_PORT})",
    )
    ap.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail immediately instead of trying subsequent ports if --port is busy",
    )
    ap.add_argument(
        "--open-browser",
        action="store_true",
        help="Open default browser automatically after binding the actual port",
    )
    return ap


def main(argv: list[str] | None = None) -> None:
    _reconfigure_utf8_stdio()
    args = build_arg_parser().parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        sys.stderr.write("Error: For security, server only binds to localhost (127.0.0.1).\n")
        sys.exit(2)

    demo_env: DemoEnvironment | None = None
    if args.demo:
        demo_env = DemoEnvironment()
        state = DeskState(demo_env=demo_env)
    else:
        claude_root = pathlib.Path(args.claude_dir).expanduser() if args.claude_dir else None
        ag_brain = pathlib.Path(args.antigravity_dir).expanduser() if args.antigravity_dir else None
        repo_path = pathlib.Path(args.repo).expanduser() if args.repo else None
        state = DeskState(
            repo_dir=repo_path,
            claude_projects_dir=(claude_root / "projects") if claude_root else None,
            claude_agents_dir=(claude_root / "agents") if claude_root else None,
            claude_sessions_dir=(claude_root / "sessions") if claude_root else None,
            antigravity_brain_dir=ag_brain,
        )

    httpd: DeskHTTPServer | None = None
    max_tries = 1 if args.strict_port or args.port == 0 else 25
    for attempt in range(max_tries):
        candidate_port = 0 if args.port == 0 else (args.port + attempt)
        try:
            httpd = DeskHTTPServer((args.host, candidate_port), state)
            break
        except OSError:
            if attempt == max_tries - 1:
                raise

    assert httpd is not None
    chosen_port = httpd.server_address[1]
    host_url = f"[{args.host}]" if ":" in args.host else args.host
    url = f"http://{host_url}:{chosen_port}"
    mode_tag = "DEMO" if state.demo_mode else "LIVE"
    print(f"[Cobalt Agent Desk v{__version__}] ({mode_tag}) Listening on {url}", flush=True)

    if args.open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n[Cobalt Agent Desk] Shutting down...", flush=True)
    finally:
        httpd.server_close()
        if demo_env is not None:
            demo_env.cleanup()


if __name__ == "__main__":
    main()
