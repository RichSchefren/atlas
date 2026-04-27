#!/usr/bin/env bash
#
# Atlas laptop setup — Rich's M5 MacBook to working-laptop parity.
#
# Idempotent + resumable. Each stage writes a checkpoint to
# ~/.atlas-laptop-setup.state. Re-running picks up where the last
# stage left off. To re-run a specific stage in isolation, pass it
# as the first arg.
#
# Stages: prereqs · python · docker · atlas · claude · syncthing ·
#         screenpipe · mcp · verify
#
# Total wall time: 90-180 min (mostly idle waits on installs).
# User-keyboard moments: 6 (sudo password, Docker launch, 1Password
# Touch ID, Obsidian welcome, Syncthing pairing, Screenpipe perms).

set -euo pipefail

LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/atlas-laptop-setup.log"
STATE_FILE="$HOME/.atlas-laptop-setup.state"
ATLAS_DIR="$HOME/Projects/atlas"
mkdir -p "$LOG_DIR" "$HOME/Projects"

# ─── Logging ────────────────────────────────────────────────────────

log()  { echo -e "\033[36m[atlas-setup]\033[0m $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "\033[32m[atlas-setup ✓]\033[0m $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "\033[33m[atlas-setup ⚠]\033[0m $*" | tee -a "$LOG_FILE"; }
err()  { echo -e "\033[31m[atlas-setup ✗]\033[0m $*" | tee -a "$LOG_FILE"; }
hr()   { echo -e "\033[2m──────────────────────────────────────────\033[0m"; }

stage_done() {
    grep -qx "$1" "$STATE_FILE" 2>/dev/null
}
mark_done() {
    echo "$1" >> "$STATE_FILE"
    ok "stage '$1' complete"
}

prompt_continue() {
    hr
    echo -e "\033[33m$*\033[0m"
    read -rp "Press ENTER when done (or Ctrl+C to abort): "
}

# ─── Pre-flight ─────────────────────────────────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
    err "This script is macOS-only."
    exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
    warn "Not on Apple Silicon ($(uname -m)). Some Homebrew paths may differ."
fi

# ─── Stage: prereqs ─────────────────────────────────────────────────

stage_prereqs() {
    if stage_done prereqs; then ok "prereqs already done"; return; fi
    log "Stage: prereqs (Homebrew + core CLI tools)"

    if ! command -v brew >/dev/null 2>&1; then
        log "Installing Homebrew (will prompt for sudo password)..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
        ok "Homebrew already installed"
    fi

    # Ensure brew is on PATH for this script + future shells
    if [[ -d /opt/homebrew/bin ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        # Ensure ~/.zprofile sources brew
        if ! grep -q "brew shellenv" "$HOME/.zprofile" 2>/dev/null; then
            echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$HOME/.zprofile"
        fi
    fi

    log "Installing core CLI tools..."
    brew install --quiet \
        git gh jq ripgrep fd bat htop watch tree wget pandoc \
        coreutils gnu-sed direnv asciinema 2>&1 | tee -a "$LOG_FILE" || true

    mark_done prereqs
}

# ─── Stage: python ──────────────────────────────────────────────────

stage_python() {
    if stage_done python; then ok "python already done"; return; fi
    log "Stage: python (3.14 + Atlas clone + venv)"

    brew install --quiet python@3.14 2>&1 | tee -a "$LOG_FILE" || true

    # Codesign the python binary so macOS TCC permissions persist
    # (per memory_homebrew_python_tcc_fix). Otherwise re-running brew
    # upgrade will keep prompting for permissions.
    PY_BIN=$(ls /opt/homebrew/Cellar/python@3.14/*/Frameworks/Python.framework/Versions/3.14/bin/python3.14 2>/dev/null | head -1)
    if [[ -n "$PY_BIN" ]]; then
        log "Codesigning $PY_BIN for stable TCC..."
        codesign -f -s - "$PY_BIN" 2>&1 | tee -a "$LOG_FILE" || true
    fi

    if [[ ! -d "$ATLAS_DIR" ]]; then
        log "Cloning Atlas to $ATLAS_DIR"
        git clone https://github.com/RichSchefren/atlas "$ATLAS_DIR"
    else
        ok "Atlas already cloned at $ATLAS_DIR"
    fi

    cd "$ATLAS_DIR"
    if [[ ! -d .venv ]]; then
        log "Creating Atlas venv..."
        python3.14 -m venv .venv
    fi
    source .venv/bin/activate
    log "Installing Atlas + dev deps (this is the longest single step, 5-10 min)..."
    pip install --quiet --upgrade pip
    pip install --quiet -e ".[dev]" 2>&1 | tee -a "$LOG_FILE"
    deactivate

    mark_done python
}

# ─── Stage: docker ──────────────────────────────────────────────────

stage_docker() {
    if stage_done docker; then ok "docker already done"; return; fi
    log "Stage: docker (Docker Desktop + Neo4j 5.26)"

    if ! command -v docker >/dev/null 2>&1; then
        log "Installing Docker Desktop via Homebrew cask..."
        brew install --quiet --cask docker 2>&1 | tee -a "$LOG_FILE" || true
        prompt_continue "Open Docker Desktop now (it should be in /Applications) and click 'Start'. Wait until the whale icon shows 'Docker Desktop is running' in the menu bar."
    else
        ok "Docker already on PATH"
    fi

    # Wait for the Docker daemon
    for i in {1..30}; do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 2
    done
    if ! docker info >/dev/null 2>&1; then
        err "Docker daemon never became responsive. Open Docker Desktop and try again."
        exit 1
    fi

    cd "$ATLAS_DIR"
    log "Starting Neo4j 5.26 (this is the second-longest step, 3-5 min for first pull)..."
    docker compose up -d 2>&1 | tee -a "$LOG_FILE"

    log "Waiting for Neo4j to come up..."
    for i in {1..30}; do
        if curl -sf http://localhost:7474 >/dev/null 2>&1; then
            ok "Neo4j healthy at http://localhost:7474"
            break
        fi
        sleep 2
    done

    mark_done docker
}

# ─── Stage: atlas ───────────────────────────────────────────────────

stage_atlas() {
    if stage_done atlas; then ok "atlas already done"; return; fi
    log "Stage: atlas (test suite + Obsidian plugin build)"

    cd "$ATLAS_DIR"
    source .venv/bin/activate

    log "Running test suite (439 tests; should take ~10 sec)..."
    if PYTHONPATH=. pytest tests/ -q 2>&1 | tee -a "$LOG_FILE" | tail -5; then
        ok "Tests passed"
    else
        err "Test suite went red. Investigate before proceeding."
        exit 2
    fi

    log "Running BusinessMemBench head-to-head (Atlas vs Graphiti vs Vanilla)..."
    PYTHONPATH=. python scripts/run_bmb.py 2>&1 | tee -a "$LOG_FILE" | tail -5 || true

    if [[ -d obsidian-plugin ]] && command -v npm >/dev/null 2>&1; then
        log "Building Obsidian plugin..."
        cd obsidian-plugin
        npm install --silent 2>&1 | tail -5 || true
        npm run build 2>&1 | tail -3 || true
        cd ..
    elif [[ -d obsidian-plugin ]]; then
        warn "npm not available; skipping Obsidian plugin build (install with: brew install node)"
    fi

    deactivate
    mark_done atlas
}

# ─── Stage: claude ──────────────────────────────────────────────────

stage_claude() {
    if stage_done claude; then ok "claude already done"; return; fi
    log "Stage: claude (Claude Code CLI + skills + agents + multi-model CLIs + 1Password)"

    # Node.js (needed for npm-installed CLIs and Obsidian plugin build)
    brew install --quiet node 2>&1 | tee -a "$LOG_FILE" || true

    # Multi-model CLIs (Codex, Gemini, Claude Code itself if not via web)
    log "Installing model CLIs (Claude Code, Codex, Gemini, Kimi)..."
    npm install --silent -g @anthropic-ai/claude-code @openai/codex @google/gemini-cli @moonshotai/kimi-cli 2>&1 | tee -a "$LOG_FILE" || true

    # 1Password CLI
    if ! command -v op >/dev/null 2>&1; then
        log "Installing 1Password CLI..."
        brew install --quiet --cask 1password 1password-cli 2>&1 | tee -a "$LOG_FILE" || true
    fi

    prompt_continue "1Password sign-in: run 'op signin' in a separate terminal, complete the Touch ID flow, then come back here."

    # Sync ~/.claude/ from a git repo if Rich uses one — otherwise
    # the laptop starts with default skills and pulls shared via the
    # team-shared symlink mechanism in ~/CLAUDE.md.
    if [[ ! -d "$HOME/.claude" ]]; then
        mkdir -p "$HOME/.claude/skills" "$HOME/.claude/agents"
        log "Created empty ~/.claude/ tree. Existing skills will populate on first Claude Code launch."
    fi

    # Trigger the shared skills mirror sync (per ~/CLAUDE.md)
    SHARED_REPO="$HOME/Obsidian/Shared/shared-claude-skills"
    if [[ -d "$SHARED_REPO" ]]; then
        log "Pulling shared team skills..."
        (cd "$SHARED_REPO" && git pull --quiet 2>/dev/null) || true
        for d in "$SHARED_REPO"/skills/*/; do
            [[ -d "$d" ]] || continue
            name="$(basename "$d")"
            target="$HOME/.claude/skills/$name"
            [[ -e "$target" ]] || ln -sn "$d" "$target" 2>/dev/null || true
        done
        ok "Shared skills mirrored as symlinks"
    fi

    mark_done claude
}

# ─── Stage: syncthing ───────────────────────────────────────────────

stage_syncthing() {
    if stage_done syncthing; then ok "syncthing already done"; return; fi
    log "Stage: syncthing OR Obsidian Sync (vault sync — your choice)"

    hr
    echo -e "\033[33mVault sync — current choice: Obsidian Sync (Rich's standing decision).\033[0m"
    echo
    echo "  1. Syncthing — peer-to-peer, no cloud, free forever."
    echo "     Tradeoff: requires both Macs online to sync."
    echo
    echo "  2. Obsidian Sync — paid Obsidian Inc service (\$8/mo), cloud-mediated."
    echo "     Tradeoff: dollars, but works when one Mac is off."
    echo "     ← DEFAULT (just press Enter)"
    echo
    echo "  3. Skip — handle vault sync manually later."
    echo

    # Allow non-interactive runs to skip via env var
    if [[ "${ATLAS_SYNC_CHOICE:-}" == "skip" ]]; then
        warn "ATLAS_SYNC_CHOICE=skip set; skipping vault-sync setup."
        log "When you decide, run: ./install.sh syncthing  (or sign in to Obsidian Sync via the Obsidian app directly)."
        if [[ ! -d "/Applications/Obsidian.app" ]]; then
            brew install --quiet --cask obsidian 2>&1 | tee -a "$LOG_FILE" || true
        fi
        mark_done syncthing
        return
    fi
    if [[ "${ATLAS_SYNC_CHOICE:-}" == "syncthing" ]]; then
        sync_choice=1
    elif [[ "${ATLAS_SYNC_CHOICE:-}" == "obsidian" ]]; then
        sync_choice=2
    else
        read -rp "Pick [1=Syncthing / 2=Obsidian Sync / 3=skip] (default: 2): " sync_choice
        sync_choice="${sync_choice:-2}"
    fi

    # Always install Obsidian.app — both Sync paths and the manual path need it
    if [[ ! -d "/Applications/Obsidian.app" ]]; then
        log "Installing Obsidian..."
        brew install --quiet --cask obsidian 2>&1 | tee -a "$LOG_FILE" || true
    fi

    if [[ "$sync_choice" == "2" ]]; then
        log "Obsidian Sync chosen. Skipping Syncthing install."
        prompt_continue "Open Obsidian, sign in to Obsidian Sync, and add the four vault remotes:
  - <your-vault-name-1>
  - Strategic-Profits
  - <your-vault-name-3>
  - <your-vault-name-4>
Wait for the initial sync to complete, then come back here."
        mark_done syncthing
        return
    fi

    if [[ "$sync_choice" == "3" ]]; then
        warn "Vault sync skipped. Run ./install.sh syncthing later when you decide."
        mark_done syncthing
        return
    fi

    # Path 1: Syncthing
    if ! command -v syncthing >/dev/null 2>&1; then
        log "Installing Syncthing via Homebrew cask (signed v2.0.14+ build)..."
        brew install --quiet syncthing 2>&1 | tee -a "$LOG_FILE" || true
    fi

    # Start Syncthing as a launchd user agent so it auto-starts
    log "Loading Syncthing user agent..."
    brew services start syncthing 2>&1 | tee -a "$LOG_FILE" || true
    sleep 3

    # Wait for the local API to be reachable
    for i in {1..15}; do
        if curl -sf http://127.0.0.1:8384 >/dev/null 2>&1; then
            ok "Syncthing UI at http://127.0.0.1:8384"
            break
        fi
        sleep 2
    done

    DEVICE_ID=$(syncthing --device-id 2>/dev/null || echo "<run 'syncthing --device-id' manually>")
    hr
    echo -e "\033[33mYour laptop's Syncthing device ID:\033[0m"
    echo -e "\033[1m$DEVICE_ID\033[0m"
    echo
    prompt_continue "On your M3 Ultra:
  1. Open Syncthing UI (http://127.0.0.1:8384 on the M3 Ultra)
  2. Add Remote Device, paste the ID above
  3. Share whichever Obsidian vault folders you want synced (substitute your own names)
  4. Back on this laptop, accept each folder share at http://127.0.0.1:8384"

    mark_done syncthing
}

# ─── Stage: screenpipe ──────────────────────────────────────────────

stage_screenpipe() {
    if stage_done screenpipe; then ok "screenpipe already done"; return; fi
    log "Stage: screenpipe (continuous screen + audio capture)"

    if ! command -v screenpipe >/dev/null 2>&1; then
        log "Installing Screenpipe..."
        brew install --quiet --cask screenpipe 2>&1 | tee -a "$LOG_FILE" || \
            curl -fsSL https://raw.githubusercontent.com/mediar-ai/screenpipe/main/install.sh | bash 2>&1 | tee -a "$LOG_FILE" || true
    fi

    hr
    echo -e "\033[33mScreenpipe needs THREE macOS permissions before it can capture:\033[0m"
    echo "  1. Screen Recording  — System Settings → Privacy & Security → Screen Recording → toggle on for 'screenpipe'"
    echo "  2. Microphone        — Privacy & Security → Microphone → toggle on for 'screenpipe'"
    echo "  3. Accessibility     — Privacy & Security → Accessibility → toggle on for 'screenpipe'"
    echo
    echo "Tip: launch Screenpipe ONCE first so it appears in those Privacy lists."
    echo "  open -a screenpipe"
    prompt_continue "Grant the three permissions, then come back here."

    log "Starting Screenpipe service..."
    nohup screenpipe > "$HOME/.screenpipe/screenpipe.log" 2>&1 &
    sleep 5

    mark_done screenpipe
}

# ─── Stage: mcp ─────────────────────────────────────────────────────

stage_mcp() {
    if stage_done mcp; then ok "mcp already done"; return; fi
    log "Stage: mcp (Slack + Stripe + 12 other MCP servers)"

    GLOBAL_MCP="$HOME/.claude/mcp-servers.json"
    if [[ -f "$GLOBAL_MCP" ]]; then
        ok "MCP config already at $GLOBAL_MCP"
    else
        log "Seeding global MCP config (you can edit this; tokens come from 1Password)..."
        cat > "$GLOBAL_MCP" <<'EOF'
{
  "mcpServers": {
    "slack": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-slack"],
      "env": {
        "SLACK_BOT_TOKEN": "op://Developer/Slack Bot Token/credential",
        "SLACK_TEAM_ID": "T04V3CSK6"
      }
    },
    "stripe": {
      "command": "npx",
      "args": ["-y", "@stripe/mcp", "--tools=all"],
      "env": {
        "STRIPE_API_KEY": "op://Developer/Stripe/credential"
      }
    },
    "atlas": {
      "command": "python",
      "args": ["-m", "atlas_core.adapters.claude_code"],
      "env": {
        "PYTHONPATH": "${HOME}/Projects/atlas",
        "ATLAS_NEO4J_URI": "bolt://localhost:7687",
        "ATLAS_NEO4J_USER": "neo4j",
        "ATLAS_NEO4J_PASSWORD": "atlasdev"
      }
    }
  }
}
EOF
        ok "Wrote starter MCP config to $GLOBAL_MCP. Add additional servers as needed."
    fi

    mark_done mcp
}

# ─── Stage: verify ──────────────────────────────────────────────────

stage_verify() {
    log "Stage: verify (smoke-test every component)"
    cd "$ATLAS_DIR" 2>/dev/null || { err "Atlas dir missing"; return 1; }
    source .venv/bin/activate 2>/dev/null || true

    hr
    log "1/8 — Atlas test suite"
    PYTHONPATH=. pytest tests/ -q 2>&1 | tail -3

    hr
    log "2/8 — AGM compliance (49/49 expected)"
    PYTHONPATH=. pytest tests/integration/test_agm_compliance.py -q 2>&1 | tail -3

    hr
    log "3/8 — BusinessMemBench (Atlas should hit 1.000)"
    PYTHONPATH=. python scripts/run_bmb.py 2>&1 | grep -E "^━━ |overall" | head -8

    hr
    log "4/8 — 1Password key reads"
    op read "op://Developer/OpenAI API Key/credential" 2>/dev/null | head -c 12 && echo "..." || warn "OpenAI key unreadable"

    hr
    log "5/8 — Multi-model CLIs"
    for cli in claude codex gemini node; do
        if command -v $cli >/dev/null 2>&1; then
            ok "$cli: $($cli --version 2>&1 | head -1)"
        else
            warn "$cli not on PATH"
        fi
    done

    hr
    log "6/8 — Docker + Neo4j"
    docker ps --format "table {{.Names}}\t{{.Status}}" | head -5

    hr
    log "7/8 — Syncthing"
    if curl -sf http://127.0.0.1:8384 >/dev/null 2>&1; then
        ok "Syncthing UI reachable"
    else
        warn "Syncthing UI not responding"
    fi

    hr
    log "8/8 — Screenpipe"
    if pgrep -fa screenpipe | grep -v grep >/dev/null 2>&1; then
        ok "Screenpipe running"
    else
        warn "Screenpipe not running (try: open -a screenpipe)"
    fi

    deactivate 2>/dev/null || true
    mark_done verify
    hr
    ok "Laptop setup complete. Welcome aboard."
}

# ─── Dispatch ───────────────────────────────────────────────────────

main() {
    log "Atlas laptop setup — log: $LOG_FILE"
    log "State checkpoint: $STATE_FILE"
    hr

    case "${1:-all}" in
        prereqs)    stage_prereqs ;;
        python)     stage_python ;;
        docker)     stage_docker ;;
        atlas)      stage_atlas ;;
        claude)     stage_claude ;;
        syncthing)  stage_syncthing ;;
        screenpipe) stage_screenpipe ;;
        mcp)        stage_mcp ;;
        verify)     stage_verify ;;
        all)
            stage_prereqs
            stage_python
            stage_docker
            stage_atlas
            stage_claude
            stage_syncthing
            stage_screenpipe
            stage_mcp
            stage_verify
            ;;
        reset)
            rm -f "$STATE_FILE"
            ok "Checkpoint cleared. Re-run ./install.sh."
            ;;
        *)
            err "Unknown stage: $1"
            err "Valid: prereqs · python · docker · atlas · claude · syncthing · screenpipe · mcp · verify · all · reset"
            exit 64
            ;;
    esac
}

main "$@"
