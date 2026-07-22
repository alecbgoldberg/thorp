"""Read-only HTTP server for the aggregation board (stdlib only)."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from thorp.board.dashboard import BOARD_HTML
from thorp.board.model import build_board
from thorp.board.reader import read_latest

logger = logging.getLogger(__name__)


class BoardSource:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def state(self) -> dict[str, Any]:
        return build_board(read_latest(self.data_dir))


class _Handler(BaseHTTPRequestHandler):
    source: BoardSource

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", BOARD_HTML.encode())
        elif path == "/api/board":
            self._respond(200, "application/json", json.dumps(self.source.state()).encode())
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
        logger.debug("http " + fmt, *args)


def build_server(host: str, port: int, source: BoardSource) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"source": source})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str, port: int, source: BoardSource) -> None:
    server = build_server(host, port, source)
    logger.info("board on http://%s:%s (data=%s)", host, server.server_address[1], source.data_dir)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
