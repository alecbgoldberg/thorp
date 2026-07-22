"""Unified UI server: one page (Board/Trading/Fills) + both data endpoints."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from thorp.board.server import BoardSource
from thorp.monitor.server import MonitorSource
from thorp.ui.dashboard import UI_HTML

logger = logging.getLogger("thorp.ui")


class _Handler(BaseHTTPRequestHandler):
    board: BoardSource
    monitor: MonitorSource

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", UI_HTML.encode())
        elif path == "/api/board":
            self._send(200, "application/json", json.dumps(self.board.state()).encode())
        elif path == "/api/state":
            self._send(200, "application/json", json.dumps(self.monitor.state()).encode())
        elif path == "/healthz":
            self._send(200, "text/plain", b"ok")
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("http " + fmt, *args)


def build_server(host: str, port: int, data_dir: Path, session_dir: Path) -> ThreadingHTTPServer:
    board = BoardSource(data_dir)
    monitor = MonitorSource(session_dir / "status.json", session_dir / "events.jsonl")
    handler = type("Bound", (_Handler,), {"board": board, "monitor": monitor})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str, port: int, data_dir: Path) -> None:
    server = build_server(host, port, data_dir, data_dir / "live")
    logger.info("UI on http://%s:%s", host, server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
