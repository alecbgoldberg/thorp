#!/bin/bash
# Install / manage the Kalshi+Pinnacle time-series collector as a headless
# launchd agent (macOS). This is the primary data collector.
#
#   deploy/install-collector.sh install     # write plist, load, start collecting
#   deploy/install-collector.sh uninstall   # stop and remove
#   deploy/install-collector.sh status      # is it running?
#   deploy/install-collector.sh logs        # tail the collector log
set -euo pipefail

LABEL="com.thorp.collector"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
RUNNER="$REPO/deploy/collector-run.sh"
LOG_OUT="$REPO/logs/collector.out.log"
LOG_ERR="$REPO/logs/collector.err.log"
DOMAIN="gui/$(id -u)"
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
    <key>ProgramArguments</key><array><string>${RUNNER}</string></array>
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
    [ -f "$REPO/config/collector.toml" ] || cp "$REPO/config/collector.example.toml" "$REPO/config/collector.toml"
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
    tail -n 40 -f "$REPO/logs/thorp.log"
    ;;
  *)
    echo "usage: $0 {install|uninstall|status|logs}"; exit 1;;
esac
