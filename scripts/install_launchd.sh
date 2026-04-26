#!/usr/bin/env bash
# Install Atlas's launchd plists.
#
# Two services:
#   com.atlas.ingestion   — every 30 minutes, runs the orchestrator
#   com.atlas.api-server  — continuous, FastAPI on port 9879
#
# Usage:
#   ./scripts/install_launchd.sh        # install + load
#   ./scripts/install_launchd.sh stop   # unload + uninstall
#
# After install, watch health:
#   tail -f ~/.atlas/health/com.atlas.ingestion.jsonl

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHAGENTS="$HOME/Library/LaunchAgents"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"

INGESTION_PLIST="$LAUNCHAGENTS/com.atlas.ingestion.plist"
API_PLIST="$LAUNCHAGENTS/com.atlas.api-server.plist"

if [ "${1:-}" = "stop" ]; then
  echo "Unloading + removing Atlas launch agents..."
  launchctl unload "$INGESTION_PLIST" 2>/dev/null || true
  launchctl unload "$API_PLIST" 2>/dev/null || true
  rm -f "$INGESTION_PLIST" "$API_PLIST"
  echo "Done."
  exit 0
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "error: $PYTHON_BIN missing. Run:  python -m venv .venv && source .venv/bin/activate && pip install -e .[dev]"
  exit 1
fi

mkdir -p "$LAUNCHAGENTS"
mkdir -p "$HOME/.atlas/health"

cat > "$INGESTION_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atlas.ingestion</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>-m</string>
    <string>atlas_core.daemon.cycle</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$REPO_ROOT</string>
    <key>NEO4J_URI</key>
    <string>bolt://localhost:7687</string>
    <key>NEO4J_USER</key>
    <string>neo4j</string>
    <key>NEO4J_PASSWORD</key>
    <string>atlasdev</string>
    <key>ATLAS_DAILY_LLM_BUDGET_USD</key>
    <string>5.0</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$REPO_ROOT</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$HOME/.atlas/health/com.atlas.ingestion.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/.atlas/health/com.atlas.ingestion.stderr.log</string>
</dict>
</plist>
EOF

cat > "$API_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.atlas.api-server</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>atlas_core.api.api_app:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>9879</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$REPO_ROOT</string>
    <key>NEO4J_URI</key>
    <string>bolt://localhost:7687</string>
    <key>NEO4J_USER</key>
    <string>neo4j</string>
    <key>NEO4J_PASSWORD</key>
    <string>atlasdev</string>
  </dict>
  <key>WorkingDirectory</key>
  <string>$REPO_ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$HOME/.atlas/health/com.atlas.api-server.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>$HOME/.atlas/health/com.atlas.api-server.stderr.log</string>
</dict>
</plist>
EOF

echo "Installed plists at:"
echo "  $INGESTION_PLIST"
echo "  $API_PLIST"

echo "Loading..."
launchctl unload "$INGESTION_PLIST" 2>/dev/null || true
launchctl unload "$API_PLIST" 2>/dev/null || true
launchctl load -w "$INGESTION_PLIST"
launchctl load -w "$API_PLIST"

echo
echo "Atlas daemons running. Health at:"
echo "  ~/.atlas/health/com.atlas.ingestion.jsonl"
echo "  ~/.atlas/health/com.atlas.api-server.stdout.log"
echo
echo "API server: http://localhost:9879/health"
echo
echo "To stop:  ./scripts/install_launchd.sh stop"
