# Atlas Quickstart

Three minutes from clone to working Atlas instance.

## Prerequisites

- Docker (any modern version — tested with 29.4)
- Python 3.10+
- ~2GB free disk for Neo4j data

## 1. Clone and start Neo4j

```bash
git clone https://github.com/RichSchefren/atlas.git
cd atlas
docker compose up -d
```

Verify:
```bash
docker ps --filter name=neo4j-atlas
# STATUS should show 'healthy' after ~30s
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7474
# Returns 200
```

Neo4j browser is now at `http://localhost:7474` (login: `neo4j` / `atlasdev`).

## 2. Install Atlas

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 3. Configure

```bash
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

## 4. Verify

```bash
# Unit tests (no Neo4j required)
pytest tests/unit -v

# Integration tests (requires running Neo4j)
pytest tests/integration -v
```

## 5. See it work

```bash
# The undeniable demo path: real Neo4j, real ledger, real Ripple cascade.
# 7 stages, ~12s wall time on first run.
./demo.sh
```

The output walks you through: planting a graph → changing a fact →
running `RippleEngine.propagate()` → showing reassessment proposals →
resolving one through adjudication → verifying the SHA-256 ledger chain.

Once you've seen the demo, point Atlas at your own data:

```bash
# Live ingest from Vault / Limitless / Screenpipe / Claude session logs
python scripts/first_real_run.py

# Or run the head-to-head benchmark matrix:
python scripts/run_bmb.py
```

## Stopping

```bash
docker compose down                # Stop Neo4j (data persists)
docker compose down -v             # Stop and erase Neo4j data
```

## Troubleshooting

**Neo4j won't start:** Port 7474 or 7687 already in use. Stop the conflicting service or edit `docker-compose.yml`.

**APOC errors:** Confirm `NEO4J_PLUGINS` includes `["apoc"]` in docker-compose.yml.

**Bolt connection refused:** Wait 30 seconds after `docker compose up` — Neo4j needs time to initialize.
