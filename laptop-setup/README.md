# M5 MacBook setup — Rich's working laptop

Brings the M5 MacBook to feature-parity with the M3 Ultra workstation
for everything except the heavy 24/7 daemons that don't make sense on
battery (Intelligence Engine pipeline, Karpathy wiki Gemma 4 ingest,
vault-search GPU service). Those stay on the M3 Ultra.

What you get on the laptop after the script finishes:

| Component | Status after install |
|---|---|
| Homebrew + core CLI tools | ✓ (git, gh, jq, ripgrep, fd, bat, htop, watch, etc.) |
| Python 3.14 (Homebrew) + venv | ✓ |
| Docker Desktop + Neo4j 5.26 + APOC | ✓ (Atlas backing store) |
| **Atlas** (this repo, full clone, tests passing) | ✓ |
| Obsidian + Obsidian plugin for Atlas | ✓ |
| **Syncthing** (replaces Obsidian Sync) | ✓ |
| **Screenpipe** (full ingest + permissions guidance) | ✓ |
| Claude Code CLI + every skill + every agent | ✓ |
| Codex 5.5, Gemini, Kimi CLIs (Ralph rotation) | ✓ |
| 1Password CLI + dev secrets via `op read` | ✓ |
| WisprFlow, Stream Deck profiles | ⚠ manual (Mac App Store / Stream Deck site) |
| Slack MCP + 12 other MCP servers | ✓ |
| Stripe / Bitly / GoHighLevel / etc. via 1Password | ✓ |

What you do NOT get on the laptop (intentional):

- Intelligence Engine 24-step pipeline — pinned to M3 Ultra; data merges via Syncthing
- vault-search daemon — heavy GPU, lives on M3 Ultra; laptop hits it over LAN/Tailscale
- Karpathy wiki Gemma 4 daemons — same reason
- Atlas's launchd ingestion plist — installs but you choose whether to enable it (off by default on laptop to save battery)

## Run it

```bash
# On the laptop:
git clone https://github.com/RichSchefren/atlas
cd atlas/laptop-setup
./install.sh
```

Total time: ~90-180 min mostly idle. The script pauses 6 times for
biometric / interactive auth (Homebrew sudo, Docker Desktop launch,
1Password Touch ID, Obsidian first-run, Screenpipe permission grants,
Syncthing device pairing).

## Stages

The script runs as discrete stages so you can resume after a failure
or skip a section that's already done:

```bash
./install.sh                # full run (default)
./install.sh prereqs        # Homebrew + core CLI
./install.sh python         # Python 3.14 + Atlas clone + venv
./install.sh docker         # Docker Desktop + Neo4j
./install.sh atlas          # Atlas tests + first-run + Obsidian plugin build
./install.sh claude         # Claude Code + skills + agents + 1Password
./install.sh syncthing      # Syncthing install + vault folder pairing
./install.sh screenpipe     # Screenpipe install + permission walkthrough
./install.sh mcp            # Slack + Stripe + 12 other MCP servers
./install.sh verify         # final smoke test of every component
```

Each stage writes a checkpoint at `~/.atlas-laptop-setup.state` so
re-running picks up where the last stage left off.

## What you do at the keyboard

The script tells you exactly when to act. Six prompts:

1. **Homebrew install** — type your laptop password once when sudo asks
2. **Docker Desktop first launch** — click "Start" when the app opens
3. **1Password CLI sign-in** — Touch ID
4. **Obsidian first run** — the script opens Obsidian; click through the welcome
5. **Syncthing pairing** — the script prints your laptop device ID; on the M3 Ultra Syncthing UI, click "Add Device" with that ID, then accept the share for each vault folder
6. **Screenpipe permissions** — System Settings → Privacy & Security → grant: Screen Recording, Microphone, Accessibility (3 toggles)

Everything else is automatic.

## After it finishes

```bash
# On the laptop:
launchctl load ~/Library/LaunchAgents/com.atlas.api-server.plist
open http://localhost:9879/health   # should return {"status":"ok"}
open obsidian://                     # vaults synced via Syncthing should appear
open ~/Projects/atlas
```

Smoke-test commands the verify stage runs for you:

```bash
PYTHONPATH=. pytest tests/ -v       # 439 passing
PYTHONPATH=. python scripts/run_bmb.py    # Atlas 1.000 vs Vanilla 0.000
op read "op://Developer/OpenAI API Key/credential" | head -c 10  # key reads
claude --version                     # Claude Code CLI
gemini --version                     # Gemini CLI (for Ralph)
docker ps | grep neo4j               # Neo4j healthy
syncthing --version                  # Syncthing
screenpipe --version                 # Screenpipe
```

## Recovery

If anything fails:

- Re-run the failing stage: `./install.sh <stage_name>`
- Reset the checkpoint: `rm ~/.atlas-laptop-setup.state && ./install.sh`
- Read the log: `tail -100 ~/Library/Logs/atlas-laptop-setup.log`
- File a tester-finding issue with the laptop-setup label
