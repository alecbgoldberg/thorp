"""Read-only ingestion of the engine's status file + event log.

Never touches engine memory (Doc 3 §3.9). Tolerant by construction: a missing
status file (engine still starting), a truncated final event-log line (crash
mid-write), and unknown event types are all handled without raising, because a
monitor that crashes on a partial read is worse than one that shows slightly
stale data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from thorp.telemetry.events import EngineStatus, Event

logger = logging.getLogger(__name__)

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)

# Bytes to read from the tail of the event log — bounds work on a large file
# while comfortably covering the number of recent events the UI shows.
_TAIL_BYTES = 256 * 1024


def read_status(path: Path) -> EngineStatus | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    if not raw.strip():
        return None
    try:
        return EngineStatus.model_validate_json(raw)
    except ValidationError as exc:
        logger.warning("status file %s failed validation: %s", path, exc)
        return None


def tail_events(path: Path, limit: int = 200) -> list[Event]:
    """Return up to ``limit`` most-recent events, oldest-first."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            block = f.read()
    except FileNotFoundError:
        return []

    lines = block.split(b"\n")
    # Drop a possibly-partial first line when we started mid-file.
    if len(block) == _TAIL_BYTES:
        lines = lines[1:]

    events: list[Event] = []
    for line in lines[-(limit + 5) :]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(_EVENT_ADAPTER.validate_json(line))
        except (ValidationError, json.JSONDecodeError):
            # Truncated final line or an unrecognized type — skip, don't crash.
            continue
    return events[-limit:]
