# Atlas Memory — Obsidian plugin

The killer UX for Atlas adjudication. Lives inside the editor Rich
already has open. Talks to the Atlas API on `localhost:9879`.

## What it does

1. **Sidebar pane** lists every pending adjudication entry. Click to
   open in the editor.
2. **Save-listener** detects when you check the Accept / Reject /
   Adjust / Demote box in an adjudication markdown and POSTs the
   decision to Atlas. Atlas applies the AGM revision, writes a
   ledger SUPERSEDE event, and archives the file.
3. **Settings tab** lets you point at a non-default Atlas API URL,
   adjudication directory, or agent ID.

No fswatch. No launchd plist required for the plugin itself (Atlas
needs the API server running, but that's a separate concern).

## Install

While this is alpha, install via Obsidian's BRAT plugin or manually:

```bash
# From the Atlas repo root
cd obsidian-plugin
npm install
npm run build
# Copy main.js + manifest.json into your vault's
# .obsidian/plugins/atlas-memory/ directory:
mkdir -p ~/Obsidian/Active-Brain/.obsidian/plugins/atlas-memory
cp main.js manifest.json ~/Obsidian/Active-Brain/.obsidian/plugins/atlas-memory/
```

Then in Obsidian → Settings → Community plugins → enable "Atlas Memory."

## Distribution roadmap

- v0.1.0 (this commit): manual install, alpha
- v0.2.0: BRAT-ready
- v0.3.0: submitted to Obsidian Community Plugins registry

## Spec

PHASE-5-AND-BEYOND.md § 1.2-ALT (the Donnie path).
