#!/usr/bin/env bash
set -euo pipefail

activate=true
if [[ "${1:-}" == "--no-activate" ]]; then
  activate=false
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--no-activate]" >&2
  exit 2
fi
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hermes_home="${HERMES_HOME:-${HOME}/.hermes}"
destination="${hermes_home}/plugins/atlas"

mkdir -p "${destination}"
cp "${script_dir}/atlas/__init__.py" "${destination}/__init__.py"
cp "${script_dir}/atlas/store.py" "${destination}/store.py"
cp "${script_dir}/plugin.yaml" "${destination}/plugin.yaml"

echo "Installed Atlas Hermes provider at ${destination}"

if [[ "${activate}" == true ]]; then
  if command -v hermes >/dev/null 2>&1; then
    hermes memory setup atlas
  else
    echo "Hermes CLI is not on PATH. After installing Hermes, run: hermes memory setup atlas"
  fi
fi
