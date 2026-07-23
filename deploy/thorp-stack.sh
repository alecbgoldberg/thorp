#!/bin/bash
# Install / manage the live SIMULATION stack as headless launchd agents:
#   engine   (python -m thorp.engine)   — samples 4 sources, sim-trades, telemetry
#   watchdog (python -m thorp.watchdog)  — dead-man switch on the engine heartbeat
#   ui       (python -m thorp.ui)        — the unified UI at http://127.0.0.1:8800
#
#   deploy/thorp-stack.sh install     # write plists, load, start all three
#   deploy/thorp-stack.sh uninstall   # stop and remove all three
#   deploy/thorp-stack.sh status      # are they running?
#   deploy/thorp-stack.sh logs        # tail the shared app log
#
# ALL SIMULATION (CLAUDE.md rule #1). caffeinate blocks idle/system sleep on AC.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
SERVICES=("engine" "watchdog" "ui")

plist_path(){ echo "$HOME/Library/LaunchAgents/com.thorp.$1.plist"; }

write_plist(){
  local svc="$1" plist; plist="$(plist_path "$svc")"
  mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.thorp.${svc}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>${UV}</string><string>run</string><string>python</string><string>-m</string><string>thorp.${svc}</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>${REPO}/logs/${svc}.out.log</string>
  <key>StandardErrorPath</key><string>${REPO}/logs/${svc}.err.log</string>
</dict></plist>
PLIST
}

case "${1:-}" in
  install)
    [ -f "$REPO/config/collector.toml" ] || cp "$REPO/config/collector.example.toml" "$REPO/config/collector.toml"
    # engine subsumes the old standalone collector daemon
    launchctl bootout "$DOMAIN/com.thorp.collector" 2>/dev/null || true
    for svc in "${SERVICES[@]}"; do
      write_plist "$svc"
      launchctl bootout "$DOMAIN/com.thorp.$svc" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$(plist_path "$svc")"
      launchctl enable "$DOMAIN/com.thorp.$svc"
      launchctl kickstart -k "$DOMAIN/com.thorp.$svc"
      echo "started com.thorp.$svc"
    done
    echo "UI -> http://127.0.0.1:8800"
    ;;
  uninstall)
    for svc in "${SERVICES[@]}"; do
      launchctl bootout "$DOMAIN/com.thorp.$svc" 2>/dev/null || true
      rm -f "$(plist_path "$svc")"
    done
    echo "removed engine/watchdog/ui"
    ;;
  status)
    for svc in "${SERVICES[@]}"; do
      if launchctl print "$DOMAIN/com.thorp.$svc" >/dev/null 2>&1; then
        state=$(launchctl print "$DOMAIN/com.thorp.$svc" | grep -m1 "state =" | tr -d ' ')
        echo "com.thorp.$svc: $state"
      else echo "com.thorp.$svc: NOT loaded"; fi
    done
    ;;
  logs)
    tail -n 40 -f "$REPO/logs/thorp.log"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status|logs}"; exit 1;;
esac
