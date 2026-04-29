.PHONY: help setup neo4j neo4j-down demo demo-messy test bench bench-agm bench-bmb doctor lint clean

help:
	@echo "Atlas — common operations"
	@echo ""
	@echo "  make setup       — create venv + install dev deps"
	@echo "  make neo4j       — start the Neo4j 5.26 container (docker compose)"
	@echo "  make neo4j-down  — stop the Neo4j container"
	@echo "  make doctor      — check the local environment is ready to run Atlas"
	@echo "  make demo        — run the end-to-end Ripple demo loop (synthetic)"
	@echo "  make demo-messy  — run the demo on real-shape vault + transcript inputs"
	@echo "  make test        — run the full pytest suite"
	@echo "  make lint        — ruff check (must be clean)"
	@echo "  make bench-agm   — run the 49-scenario AGM compliance suite"
	@echo "  make bench-bmb   — run the BusinessMemBench head-to-head matrix"
	@echo "  make bench       — run both benchmarks back-to-back"
	@echo "  make clean       — remove caches, *.pyc, and local benchmark output"

setup:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e .[dev] && pip install ruff
	@echo ""
	@echo "Setup complete. Next: 'make neo4j' then 'make demo'."

neo4j:
	docker compose up -d neo4j
	@echo "Waiting for Neo4j to accept connections on :7687 ..."
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do \
	  if nc -z localhost 7687 2>/dev/null; then echo "  Neo4j up."; exit 0; fi; \
	  sleep 2; \
	done; \
	echo "  Neo4j did not come up in 30s — check 'docker compose logs neo4j'."; exit 1

neo4j-down:
	docker compose down

doctor:
	@PYTHONPATH=. .venv/bin/python scripts/doctor.py 2>/dev/null || \
	  PYTHONPATH=. python3 scripts/doctor.py

demo:
	@./demo.sh

demo-messy:
	@PYTHONPATH=. .venv/bin/python scripts/demo_messy.py 2>/dev/null || \
	  PYTHONPATH=. python3 scripts/demo_messy.py

adjudicate:
	@PYTHONPATH=. .venv/bin/python scripts/adjudicate.py --report 2>/dev/null || \
	  PYTHONPATH=. python3 scripts/adjudicate.py --report

adjudicate-apply:
	@PYTHONPATH=. .venv/bin/python scripts/adjudicate.py --all 2>/dev/null || \
	  PYTHONPATH=. python3 scripts/adjudicate.py --all

test:
	@PYTHONPATH=. .venv/bin/python -m pytest tests/ -v 2>/dev/null || \
	  PYTHONPATH=. python3 -m pytest tests/ -v

lint:
	@.venv/bin/ruff check atlas_core tests benchmarks scripts 2>/dev/null || \
	  ruff check atlas_core tests benchmarks scripts

bench-agm:
	@PYTHONPATH=. .venv/bin/python scripts/run_agm_compliance.py 2>/dev/null || \
	  PYTHONPATH=. python3 scripts/run_agm_compliance.py

bench-bmb:
	@PYTHONPATH=. .venv/bin/python scripts/run_bmb.py 2>/dev/null || \
	  PYTHONPATH=. python3 scripts/run_bmb.py

bench: bench-agm bench-bmb

clean:
	rm -rf .ruff_cache .pytest_cache .hypothesis .mypy_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
