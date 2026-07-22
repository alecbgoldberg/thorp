"""Unified UI entrypoint: ``python -m thorp.ui --open``.

Board / Trading / Fills tabs in one page. Run the engine
(``python -m thorp.engine``) alongside to populate it.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from thorp.common.logging_setup import configure_logging
from thorp.ui.server import serve


def main() -> None:
    parser = argparse.ArgumentParser("thorp-ui", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    configure_logging()
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()
    serve(args.host, args.port, args.data_dir)


if __name__ == "__main__":
    main()
