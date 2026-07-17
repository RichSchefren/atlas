#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE="$ROOT/atlas-memory-gbrain-0.1.0.tgz"
command -v node >/dev/null || { echo "Node.js is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 1; }
cd "$ROOT"
shasum -a 256 -c CHECKSUMS.sha256
npm install --global "$PACKAGE"
echo "Atlas for GBrain installed. Run: atlas-gbrain status"
