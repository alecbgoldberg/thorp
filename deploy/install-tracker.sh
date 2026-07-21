#!/bin/bash
# Install / manage the MLB tracker as a headless launchd agent (macOS).
#
#   deploy/install-tracker.sh install     # write plist, load, start
#   deploy/install-tracker.sh uninstall   # stop and remove
#   deploy/install-tracker.sh status      # is it running?
#   deploy/install-tracker.sh logs        # tail the tracker log
#
# It runs under your user account (a LaunchAgent), wrapped in caffeinate so the
# Mac won't idle-sleep while it captures. See deploy/README.md for the caveats.
set -euo pipefail

LABEL="com.thorp.tracker"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
RUNNER="$REPO/deploy/tracker-run.sh"
LOG_OUT="$REPO/logs/tracker.out.log"
LOG_ERR="$REPO/logs/tracker.err.log"
DOMAIN="gui/$(id -u)"        # modern launchctl domain (per-user GUI session)
SERVICE="$DOMAIN/$LABEL"

write_plist() {
  mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
  chmod +x "$RUNNER"
  cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${RUNNER}</string>
    </array>
    <key>WorkingDirectory</key><string>${REPO}</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>60</integer>
    <key>ProcessType</key><string>Background</string>
    <key>StandardOutPath</key><string>${LOG_OUT}</string>
    <key>StandardErrorPath</key><string>${LOG_ERR}</string>
</dict>
</plist>
PLIST
  echo "wrote $PLIST"
}

case "${1:-}" in
  install)
    if [ ! -f "$REPO/config/tracker.toml" ]; then
      echo "note: config/tracker.toml missing — copying from example"
      cp "$REPO/config/tracker.example.toml" "$REPO/config/tracker.toml"
    fi
    write_plist
    launchctl bootout "$SERVICE" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    launchctl enable "$SERVICE"
    launchctl kickstart -k "$SERVICE"
    echo "bootstrapped and started. Tail logs with: $0 logs"
    ;;
  uninstall)
    launchctl bootout "$SERVICE" 2>/dev/null || true
    rm -f "$PLIST"
    echo "booted out and removed $PLIST"
    ;;
  status)
    if launchctl print "$SERVICE" >/dev/null 2>&1; then
      launchctl print "$SERVICE" | grep -iE "state =|pid =|last exit" | sed 's/^/  /'
    else
      echo "NOT loaded (run: $0 install)"
    fi
    ;;
  logs)
    echo "== $LOG_OUT / logs/tracker.log =="
    tail -n 40 -f "$REPO/logs/tracker.log" 2>/dev/null || tail -n 40 -f "$LOG_OUT"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status|logs}"; exit 1;;
esac
