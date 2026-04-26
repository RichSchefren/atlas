#!/usr/bin/env bash
# Initialize the GitHub remote, push master, and trigger CI in one go.
#
# Usage:
#   ./scripts/push_to_github.sh ORG/REPO
#   ./scripts/push_to_github.sh rich-schefren/atlas
#
# Prerequisites:
#   1. Repo created on github.com/ORG/REPO (via `gh repo create` or web UI)
#   2. `gh auth status` returns an authenticated session
#   3. Local working tree is clean (commit any pending changes first)

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 ORG/REPO  (e.g., rich-schefren/atlas)"
  exit 1
fi

REPO="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Sanity: clean tree
if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree has uncommitted changes. Commit or stash first."
  git status --short
  exit 1
fi

# Replace <placeholder> first
if grep -rq "<placeholder>" --include="*.md" --include="*.html" . 2>/dev/null; then
  echo "Replacing <placeholder> → $REPO across the repo..."
  ./scripts/replace_placeholder.sh "$REPO"
  git add -A
  git -c user.email="rich@strategicprofits.com" \
      -c user.name="Richard Schefren" \
      commit -m "Replace <placeholder> with $REPO ahead of public push"
fi

# Add remote if missing, otherwise update
if git remote get-url origin > /dev/null 2>&1; then
  echo "origin already set to: $(git remote get-url origin)"
else
  git remote add origin "git@github.com:$REPO.git"
  echo "Added remote: git@github.com:$REPO.git"
fi

echo
echo "Pushing master to origin..."
git push -u origin master

echo
echo "Done. CI should be running at:"
echo "  https://github.com/$REPO/actions"
echo
echo "Watch CI complete:"
echo "  gh run watch -R $REPO"
