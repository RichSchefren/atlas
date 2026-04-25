# Atlas Quickstart

Three minutes from clone to working Atlas instance.

## Prerequisites

- Docker (any modern version — tested with 29.4)
- Python 3.10+
- ~2GB free disk for Neo4j data

## 1. Clone and start Neo4j

```bash
git clone https://github.com/<your-fork>/atlas.git
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

## 5. First ingestion (Phase 2 Week 1+ — once available)

```bash
python -m atlas_core.examples.business_ontology_demo
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
