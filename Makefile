.PHONY: dev test lint typecheck fmt run-local docker-up docker-down clean

PYTHON ?= python3
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python

dev: $(VENV)/.installed  ## Create venv and install dev + optional deps
$(VENV)/.installed:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,ai,mcp,otel]"
	touch $@

test: dev  ## Run unit tests
	$(PY) -m pytest -m "not integration and not eval"

test-all: dev  ## Run every test marker
	$(PY) -m pytest

lint: dev  ## Ruff lint
	$(PY) -m ruff check sentinel tests

fmt: dev  ## Ruff format
	$(PY) -m ruff format sentinel tests
	$(PY) -m ruff check --fix sentinel tests

typecheck: dev  ## Mypy
	$(PY) -m mypy sentinel

check: lint typecheck test  ## What CI runs

run-local: dev  ## Run the sentinel locally against config/sentinel.yaml
	$(PY) -m sentinel

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

clean:
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache *.egg-info build dist
	find . -type d -name __pycache__ -exec rm -rf {} +
