# Local pre-deploy gate (Doc 6 §1): run before anything reaches CANARY/PRODUCTION.
.PHONY: check lint type test cov

check: lint type test

lint:
	uv run ruff check src tests research

type:
	uv run mypy
	uv run mypy research/lead_lag/study.py

test:
	uv run pytest -q

cov:
	uv run coverage run -m pytest -q && uv run coverage report -m
