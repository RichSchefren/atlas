#!/usr/bin/env bash
# Run the full BusinessMemBench matrix with all keyed adapters
# enabled. Reads keys from the environment or 1Password, runs the
# benchmark against every system that's both installed and
# configured, writes the results to /tmp/bmb_full.json.
#
# Usage:
#   ./scripts/run_full_matrix_with_keys.sh
#
# Required env vars (read from the shell, or via `op run --env-file`):
#   OPENAI_API_KEY     — enables Mem0 and Letta
#   MEMORI_API_KEY     — enables Memori (signup at app.memorilabs.ai)
#
# Optional:
#   KUMIHO_API_KEY     — enables Kumiho (when their Python client ships)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "warn: OPENAI_API_KEY not set — Mem0 and Letta will skip"
  echo "       Try:  export OPENAI_API_KEY=\$(op read 'op://Developer/OpenAI/credential')"
fi

if [ -z "${MEMORI_API_KEY:-}" ]; then
  echo "warn: MEMORI_API_KEY not set — Memori will skip"
fi

source .venv/bin/activate
PYTHONPATH=. python scripts/run_bmb.py --out /tmp/bmb_full.json

echo
echo "Full matrix written → /tmp/bmb_full.json"
echo
echo "Pretty-print the result:"
echo "  python -c 'import json; d=json.load(open(\"/tmp/bmb_full.json\"));"
echo "    [print(f\"{k:24} {v.get(\\\"overall_mean_score\\\", \\\"SKIP\\\")}\") for k,v in d.items()]'"
