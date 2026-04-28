#!/usr/bin/env bash
# install_qa_cron.sh — install a macOS launchd job that runs qa_site.py
# every 4 hours and logs failures.
#
# Run once:
#   ./scripts/install_qa_cron.sh
#
# Uninstall:
#   launchctl unload ~/Library/LaunchAgents/com.atlas.qa.plist
#   rm ~/Library/LaunchAgents/com.atlas.qa.plist

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.atlas.qa.plist"
LOG="$HOME/.atlas/qa.log"

mkdir -p "$(dirname "$LOG")"
mkdir -p "$(dirname "$PLIST")"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atlas.qa</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>${REPO}/scripts/qa_site.py</string>
    <string>--quiet</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>13</integer></dict>
    <dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>13</integer></dict>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>13</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>13</integer></dict>
    <dict><key>Hour</key><integer>16</integer><key>Minute</key><integer>13</integer></dict>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>13</integer></dict>
  </array>
  <key>StandardOutPath</key>
  <string>${LOG}</string>
  <key>StandardErrorPath</key>
  <string>${LOG}</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
EOF

# Reload (unload first so we pick up changes if re-running)
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed: $PLIST"
echo "Log:       $LOG"
echo "Schedule:  6x daily at HH:13 (00, 04, 08, 12, 16, 20)"
echo
echo "Test now:"
echo "  python3 ${REPO}/scripts/qa_site.py"
echo
echo "Check the next fire time:"
echo "  launchctl list | grep com.atlas.qa"
