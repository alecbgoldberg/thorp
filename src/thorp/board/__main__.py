"""Aggregation board entrypoint.

    python -m thorp.board --open      # serve the board, open a browser tab
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from thorp.board.server import BoardSource, serve
from thorp.common.logging_setup import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser("thorp-board", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8799)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--open", action="store_true", help="open a browser tab")
    args = parser.parse_args()
    configure_logging()

    source = BoardSource(args.data_dir)
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    serve(args.host, args.port, source)


if __name__ == "__main__":
    main()
