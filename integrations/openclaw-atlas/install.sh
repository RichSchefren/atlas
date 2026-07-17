#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE="$ROOT/atlas-memory-openclaw-0.2.0.tgz"
command -v openclaw >/dev/null || { echo "openclaw is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required (or configure pythonCommand after install)" >&2; exit 1; }
cd "$ROOT"
shasum -a 256 -c CHECKSUMS.sha256
openclaw plugins install "$PACKAGE" --force
openclaw config set plugins.slots.memory atlas-memory
openclaw plugins inspect atlas-memory --runtime --json
echo "Atlas cognitive memory installed. Restart the OpenClaw gateway."
