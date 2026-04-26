# arxiv submission package

Source files for the Atlas paper, ready for arxiv upload.

## Files

- `atlas.tex` — main paper, compiled from `paper/atlas.md` via pandoc
- `appendix-a.tex` — AGM compliance reproducibility artifact
- (To add before submission: `references.bib` once full citations are pulled)

## Re-build the bundle

```bash
pandoc paper/atlas.md -o paper/arxiv/atlas.tex --standalone \
    -V documentclass=article -V geometry:margin=1in -V fontsize=11pt
pandoc paper/appendix-a-agm-compliance.md -o paper/arxiv/appendix-a.tex --standalone \
    -V documentclass=article
tar -czf paper/arxiv/atlas-arxiv.tar.gz -C paper/arxiv atlas.tex appendix-a.tex
```

## Submission steps

1. Build the tarball (above).
2. Upload `atlas-arxiv.tar.gz` at https://arxiv.org/submit
3. Choose categories: `cs.AI` (primary), `cs.CL` (cross-list)
4. arxiv compiles server-side; if it fails, the build log is in your dashboard
5. Once accepted, replace `<placeholder>` URLs in the paper with the assigned arxiv ID

## Local PDF preview (optional)

If you have MacTeX or texlive installed locally:

```bash
cd paper/arxiv
xelatex atlas.tex && xelatex atlas.tex   # second pass for refs
open atlas.pdf
```

Without LaTeX locally, just use the GitHub markdown render of `paper/atlas.md` for review — content is identical.
