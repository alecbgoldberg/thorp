"""Monitor entrypoint.

Live (default) — point it at a running engine session's files:
    python -m thorp.monitor --session-dir data/live

Demo — see the cockpit working now, before the engine exists:
    python -m thorp.monitor --demo
"""

from __future__ import annotations

import argparse
import logging
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from thorp.monitor.demo import run_demo
from thorp.monitor.server import MonitorSource, serve


def main() -> None:
    parser = argparse.ArgumentParser("thorp-monitor", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--session-dir",
        type=Path,
        default=Path("data/live"),
        help="directory holding the engine's status.json + events.jsonl",
    )
    parser.add_argument("--status", type=Path, help="override status file path")
    parser.add_argument("--events", type=Path, help="override event-log path")
    parser.add_argument("--demo", action="store_true", help="run a synthetic sim session")
    parser.add_argument("--open", action="store_true", help="open a browser tab")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    session_dir = args.session_dir
    stop: threading.Event | None = None
    demo_thread: threading.Thread | None = None
    if args.demo:
        session_dir = Path(f"data/demo/{datetime.now(UTC):%Y%m%dT%H%M%S}")
        session_dir.mkdir(parents=True, exist_ok=True)
        stop = threading.Event()
        demo_thread = threading.Thread(
            target=run_demo, args=(session_dir, stop), kwargs={"seed": args.seed}, daemon=True
        )
        demo_thread.start()
        logging.getLogger("thorp.monitor").info("demo session writing to %s", session_dir)

    status_path = args.status or session_dir / "status.json"
    events_path = args.events or session_dir / "events.jsonl"
    source = MonitorSource(status_path, events_path)

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    try:
        serve(args.host, args.port, source)
    finally:
        if stop is not None:
            stop.set()
        if demo_thread is not None:
            demo_thread.join(timeout=2)


if __name__ == "__main__":
    main()
