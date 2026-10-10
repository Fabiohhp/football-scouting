.PHONY: help setup lint format test all data model dq verify-statsbomb download-statsbomb \
	download-transfermarkt convert-statsbomb validate-statsbomb coverage-report build-tables \
	links database dictionary notebooks

help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

setup:  ## Create the virtual environment from uv.lock
	uv sync --locked

lint:  ## Check code style and formatting
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

test:  ## Run the test suite (network tests excluded)
	uv run pytest

all: data model dq  ## Everything: collect, model, test the data

data: download-statsbomb download-transfermarkt convert-statsbomb validate-statsbomb coverage-report  ## Phase 1: collect and convert (idempotent)

model: build-tables links database dictionary  ## Phase 2: processed tables, links, DuckDB, dictionary

dq:  ## Data quality tests on data/processed
	uv run pytest -m data

verify-statsbomb:  ## Verify StatsBomb coverage and estimate download size (metadata only)
	uv run python scripts/verify_statsbomb.py

download-statsbomb:  ## Download StatsBomb raw JSON (resumable, size-checked)
	uv run python scripts/download_statsbomb.py

download-transfermarkt:  ## Download Transfermarkt CSV tables (records a manifest)
	uv run python scripts/download_transfermarkt.py

convert-statsbomb:  ## Convert StatsBomb raw JSON to interim Parquet (FORCE=1 to rebuild)
	uv run python scripts/convert_statsbomb.py $(if $(FORCE),--force,)

validate-statsbomb:  ## Deep check: interim Parquet vs raw JSON (key paths, counts, xG)
	uv run python scripts/validate_statsbomb_parquet.py

coverage-report:  ## Write reports/coverage_report.md
	uv run python scripts/coverage_report.py

build-tables:  ## Processed StatsBomb + Transfermarkt tables (data/processed/)
	uv run python scripts/build_model.py

links:  ## Link StatsBomb matches, teams and players to Transfermarkt
	uv run python scripts/link_entities.py

database:  ## DuckDB database with one view per processed table
	uv run python scripts/build_database.py

dictionary:  ## Regenerate docs/DATA_DICTIONARY.md (fails on undocumented columns)
	uv run python scripts/data_dictionary.py

notebooks:  ## Re-run every notebook in place (needs `make model`)
	uv run jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb
