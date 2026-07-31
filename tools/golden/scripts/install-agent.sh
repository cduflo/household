#!/bin/bash
# Keep the command station running, and bring it back after a reboot.
#
# Only the *server* is a LaunchAgent. The sweep stays in cron deliberately:
# LaunchAgents load into a logged-in GUI session, so at the login window, or
# after a reboot where nobody logged back in, a launchd sweep would not run at
# all -- whereas cron is a system daemon and runs regardless. Trading "misses
# runs while asleep" for "misses runs while logged out" is not an upgrade.
set -euo pipefail

REPO="/Users/chrisduflo/golden-watch"
LABEL="com.chrisduflo.golden-watch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PORT="${1:-8420}"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$REPO/.venv/bin/python</string>
    <string>-m</string><string>gw.cli</string>
    <string>serve</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <!-- Not a bare <true/>: that restarts on every exit including a port
       collision, which becomes a silent respawn loop. -->
  <key>KeepAlive</key>
  <dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$REPO/serve.log</string>
  <key>StandardErrorPath</key><string>$REPO/serve.log</string>
</dict>
</plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Loaded $LABEL."
echo "Command station: http://127.0.0.1:$PORT/"
echo
echo "  stop:    launchctl unload $PLIST"
echo "  start:   launchctl load $PLIST"
echo "  logs:    tail -f $REPO/serve.log"
