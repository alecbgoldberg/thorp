"""Leveled logging + a dedicated fills log (operator request).

``configure_logging`` gives every entrypoint the same readable, leveled output:

- **Console** — human-readable, level-tagged (INFO / WARNING / ERROR), so what's
  happening and what's wrong are visible at a glance.
- **``logs/thorp.log``** — the same stream, rotating, for after-the-fact review.
- **``logs/fills.log``** — fills *only*, one clean line each, in their own file.
  Fills also appear on the console/main log (they propagate), but this file is a
  pure, greppable trade blotter.

Idempotent: calling it twice won't double-log. The fills blotter is written via
``log_fill`` so the format is defined in one place.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from pathlib import Path

FILLS_LOGGER_NAME = "thorp.fills"

_CONSOLE_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"
_FILL_FMT = "%(asctime)s %(message)s"

_MAX_BYTES = 20 * 1024 * 1024
_BACKUPS = 5

_configured = False


def configure_logging(level: str | int = "INFO", log_dir: Path = Path("logs")) -> None:
    """Set up console + rotating file logging and the separate fills blotter."""
    global _configured
    if _configured:
        return
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    main_file = RotatingFileHandler(
        log_dir / "thorp.log", maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    main_file.setFormatter(formatter)
    root.addHandler(main_file)

    # Fills logger: its own file (fills only), but still propagates so fills are
    # also visible on the console and in thorp.log.
    fills = logging.getLogger(FILLS_LOGGER_NAME)
    fills.setLevel(logging.INFO)
    fills_file = RotatingFileHandler(
        log_dir / "fills.log", maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    fills_file.setFormatter(logging.Formatter(_FILL_FMT, datefmt=_DATE_FMT))
    fills.addHandler(fills_file)

    _configured = True


def reset_logging_for_tests() -> None:
    """Test-only: drop handlers so a subsequent configure re-runs cleanly."""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    fills = logging.getLogger(FILLS_LOGGER_NAME)
    for handler in list(fills.handlers):
        fills.removeHandler(handler)
        handler.close()
    _configured = False


def fills_logger() -> logging.Logger:
    return logging.getLogger(FILLS_LOGGER_NAME)


def log_fill(
    *,
    market_key: str,
    side: str,
    price: Decimal,
    size: int,
    fee: Decimal,
    liquidity: str,
    mode: str,
    order_id: str = "",
    ts: datetime | None = None,
) -> None:
    """Write one readable line to the fills blotter (and, via propagation, the
    console/main log). Kept as the single definition of the fill line format."""
    when = (ts or datetime.now(UTC)).strftime("%H:%M:%S")
    side_txt = side.replace("_", " ")
    fills_logger().info(
        "FILL [%s] %-28s %-8s %3d @ %s  fee=%s  %-5s  (%s%s)",
        mode,
        market_key,
        side_txt,
        size,
        f"{price:.2f}",
        f"{fee:.2f}",
        liquidity,
        f"order={order_id} " if order_id else "",
        when,
    )
