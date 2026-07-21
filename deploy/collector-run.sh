#!/bin/bash
# Wrapper launchd runs to keep the Kalshi+Pinnacle collector alive headless.
# caffeinate -is prevents idle/system sleep while it runs (on AC; see README).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

exec /usr/bin/caffeinate -is "$UV" run python -m thorp.collector --config config/collector.toml
