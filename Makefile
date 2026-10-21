PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
UV ?= uv

.DEFAULT_GOAL := help
.PHONY: help install test lint typecheck check eval eval-live demo validate sop api worker clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package and the dev dependencies
	$(UV) venv
	$(UV) pip install -e ".[dev]"

test:  ## Run the test suite
	$(PYTHON) -m pytest -q

lint:  ## Check the formatting and the lint rules
	$(PYTHON) -m ruff check .

typecheck:  ## Run the type checker
	$(PYTHON) -m mypy src

check: lint typecheck test  ## Everything CI runs

eval:  ## Run the evaluation scenarios against the fake model
	$(PYTHON) -m freight_agent.cli eval

eval-live:  ## Run the evaluation scenarios against the real model (needs OPENAI_API_KEY)
	$(PYTHON) -m freight_agent.cli eval --real-llm

demo:  ## Replay the assessment's situation
	$(PYTHON) -m freight_agent.cli demo

validate:  ## Check the procedure corpus
	$(PYTHON) -m freight_agent.cli validate

sop:  ## Show the procedures that apply to a client
	$(PYTHON) -m freight_agent.cli sop $(CLIENT)

api:  ## Run the ingest API
	$(PYTHON) -m uvicorn freight_agent.api.app:app --reload --port 8000

worker:  ## Run the timer worker (needs shared stores to see the API's timers)
	$(PYTHON) -m freight_agent.workers.timer_worker

clean:  ## Remove the caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -name "__pycache__" -type d -exec rm -rf {} +
