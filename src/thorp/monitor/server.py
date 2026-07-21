"""Read-only HTTP server for the dashboard (stdlib only, no web framework).

Serves the dashboard page and a ``/api/state`` JSON endpoint that reprojects the
engine's status file + event-log tail each request. A separate, read-only
process by design (Doc 3 §3.9): it observes files, never the engine's memory, so
it works even if the engine is wedged and cannot itself perturb trading.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from thorp.monitor.dashboard import DASHBOARD_HTML
from thorp.monitor.model import build_view
from thorp.monitor.reader import read_status, tail_events

logger = logging.getLogger(__name__)


class MonitorSource:
    """Where the dashboard reads from: one engine session's two files."""

    def __init__(self, status_path: Path, events_path: Path) -> None:
        self.status_path = status_path
        self.events_path = events_path

    def state(self) -> dict[str, Any]:
        status = read_status(self.status_path)
        events = tail_events(self.events_path)
        return build_view(status, events, datetime.now(UTC))


class _Handler(BaseHTTPRequestHandler):
    source: MonitorSource  # set on the subclass created in serve()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", DASHBOARD_HTML.encode())
        elif path == "/api/state":
            body = json.dumps(self.source.state()).encode()
            self._respond(200, "application/json", body)
        elif path == "/healthz":
            self._respond(200, "text/plain", b"ok")
        else:
            self._respond(404, "text/plain", b"not found")

    def _respond(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("http %s - " + fmt, self.address_string(), *args)


def build_server(host: str, port: int, source: MonitorSource) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"source": source})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str, port: int, source: MonitorSource) -> None:
    server = build_server(host, port, source)
    actual = server.server_address[1]
    logger.info("monitor on http://%s:%s  (status=%s)", host, actual, source.status_path)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
