"""Leveled logging + the separate fills blotter (operator request)."""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from thorp.common.logging_setup import (
    configure_logging,
    log_fill,
    reset_logging_for_tests,
)


@pytest.fixture(autouse=True)
def _isolate_logging() -> None:
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()


def test_configure_creates_log_files(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path)
    logging.getLogger("thorp.test").warning("something")
    for h in logging.getLogger().handlers:
        h.flush()
    assert (tmp_path / "thorp.log").exists()
    content = (tmp_path / "thorp.log").read_text()
    assert "WARNING" in content and "something" in content


def test_fills_go_to_separate_file(tmp_path: Path) -> None:
    configure_logging(log_dir=tmp_path)
    log_fill(
        market_key="KXMLBGAME-26JUL20-NYYBOS",
        side="buy_yes",
        price=Decimal("0.41"),
        size=3,
        fee=Decimal("0.05"),
        liquidity="taker",
        mode="SIMULATION",
        order_id="ord-9",
        ts=datetime(2026, 7, 20, 18, 30, 0, tzinfo=UTC),
    )
    for h in logging.getLogger("thorp.fills").handlers:
        h.flush()

    fills = (tmp_path / "fills.log").read_text()
    assert "FILL" in fills
    assert "KXMLBGAME-26JUL20-NYYBOS" in fills
    assert "buy yes" in fills
    assert "SIMULATION" in fills

    # Fills also propagate to the main log (visible on console too).
    main = (tmp_path / "thorp.log").read_text()
    assert "FILL" in main


def test_http_client_logging_is_quieted(tmp_path: Path) -> None:
    # API keys ride in request URLs (OddsPapi ?apiKey=...); httpx/httpcore must
    # not log them at INTO the log files.
    configure_logging(log_dir=tmp_path)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_configure_is_idempotent(tmp_path: Path) -> None:
    from logging.handlers import RotatingFileHandler

    configure_logging(log_dir=tmp_path)
    configure_logging(log_dir=tmp_path)
    # The second call is a no-op: our handlers are not duplicated. (Counting our
    # own handlers, not all root handlers — the test runner adds its own.)
    root_files = [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]
    fills_files = logging.getLogger("thorp.fills").handlers
    assert len(root_files) == 1
    assert len(fills_files) == 1
