#!/bin/bash
# Wrapper launchd runs to keep the MLB tracker alive headless.
#
# `caffeinate -is` prevents idle + system sleep while the tracker runs, so it
# keeps capturing when the Mac would otherwise nap (on AC power; a hard
# lid-close on battery can still suspend — for true 24/7 use a small always-on
# box, see deploy/README.md). exec so caffeinate is the supervised process and
# launchd's KeepAlive tracks it correctly.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

exec /usr/bin/caffeinate -is "$UV" run python -m thorp.tracker --config config/tracker.toml
