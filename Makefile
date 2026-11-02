.PHONY: dev test lint typecheck fmt run-local docker-up docker-down clean

PYTHON ?= python3
VENV   ?= .venv
PY     := $(VENV)/bin/python
# Use `python -m pip` not `.venv/bin/pip` — the pip wrapper's shebang hardcodes
# an absolute path to .venv/bin/python, which breaks if the repo folder moves.
PIP    := $(PY) -m pip
LINT_PATHS := argus tests products

dev: $(VENV)/.installed  ## Create venv and install dev + optional deps
$(VENV)/.installed:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,ai,mcp,otel,metrics,integration]"
	touch $@

test: dev  ## Run unit tests
	$(PY) -m pytest -m "not integration and not eval"

test-all: dev  ## Run every test marker
	$(PY) -m pytest

lint: dev  ## Ruff lint
	$(PY) -m ruff check $(LINT_PATHS)

fmt: dev  ## Ruff format
	$(PY) -m ruff format $(LINT_PATHS)
	$(PY) -m ruff check --fix $(LINT_PATHS)

typecheck: dev  ## Mypy
	$(PY) -m mypy argus products

check: lint typecheck test  ## What CI runs

run-local: dev  ## Run the argus locally against config/argus.yaml
	$(PY) -m argus

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache *.egg-info build dist
	find . -type d -name __pycache__ -exec rm -rf {} +
