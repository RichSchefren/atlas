#!/usr/bin/env bash
# Replace `<placeholder>` with the real GitHub org/repo across the
# entire repo. Run once when the repo goes public.
#
# Usage:
#   ./scripts/replace_placeholder.sh ORG/REPO
#   ./scripts/replace_placeholder.sh rich-schefren/atlas
#
# After this runs, every README, paper draft, X thread, Show HN
# post, landing page, demo, and outreach email points at the real
# URL. No more grep <placeholder> anywhere in the repo.

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 ORG/REPO  (e.g., rich-schefren/atlas)"
  exit 1
fi

REPO="$1"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$ROOT"

# Files we update (everything except node_modules, .venv, .git, build artifacts)
FILES=$(grep -rl "<placeholder>" \
    --include="*.md" --include="*.html" --include="*.py" \
    --include="*.toml" --include="*.yml" --include="*.yaml" \
    --include="*.tex" \
    . 2>/dev/null | grep -v ".venv\|node_modules\|.git/\|paper/arxiv/atlas-arxiv.tar.gz" || true)

if [ -z "$FILES" ]; then
  echo "No <placeholder> tokens found. Already replaced?"
  exit 0
fi

echo "Replacing <placeholder> → $REPO in:"
echo "$FILES" | sed 's/^/  /'
echo

while IFS= read -r file; do
  # macOS sed needs an empty backup arg
  sed -i '' "s|<placeholder>|$REPO|g" "$file"
done <<< "$FILES"

# Re-build the arxiv tarball with the new URLs
if command -v pandoc > /dev/null && [ -f paper/atlas.md ]; then
  echo "Rebuilding arxiv tarball with the real URL..."
  pandoc paper/atlas.md -o paper/arxiv/atlas.tex --standalone \
    -V documentclass=article -V geometry:margin=1in -V fontsize=11pt
  pandoc paper/appendix-a-agm-compliance.md -o paper/arxiv/appendix-a.tex \
    --standalone -V documentclass=article
  tar -czf paper/arxiv/atlas-arxiv.tar.gz -C paper/arxiv atlas.tex appendix-a.tex
fi

echo
echo "Done. Review the changes:"
echo "  git diff"
echo "Commit when satisfied:"
echo "  git add -A && git commit -m 'Replace <placeholder> with $REPO'"
