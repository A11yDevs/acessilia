# Local test entry points; see docs/testing.md for the workflow.
#
# `test-all` runs the main suite with four workers after the isolation fixes
# tracked by #448 (PR 2); docstruct and SDK stay sequential because they are
# fast. Use `uv run pytest ...` directly for anything these targets do not cover.

UV ?= uv
PYTEST ?= $(UV) run pytest
PYTEST_FLAGS ?= -m "not e2e"
CORE_JOBS ?= 4
CORE_DIST ?= worksteal
CORE_PARALLEL ?= -n $(CORE_JOBS) --dist $(CORE_DIST)
DURATIONS ?= 25
COVERAGE_DIR ?= var/coverage

.DEFAULT_GOAL := help

.PHONY: help test-file test-failed test-all lint coverage

help:
	@printf '%s\n' \
		'make test-file F=tests/test_example.py  run one file or node id' \
		'make test-failed                        rerun the tests that failed last time' \
		'make test-all                           run the main suite (4 workers), docstruct, SDK and libs/core' \
		'make lint                               run Ruff against the shrinking baseline (scripts/check_ruff_baseline.py)' \
		'make coverage                           run tests with branch coverage per component (var/coverage/)'

lint:
	$(UV) run python scripts/check_ruff_baseline.py

coverage:
	@mkdir -p "$(COVERAGE_DIR)/app" "$(COVERAGE_DIR)/docstruct" "$(COVERAGE_DIR)/sdk" "$(COVERAGE_DIR)/core"; \
	status=0; \
	COVERAGE_FILE="$(CURDIR)/$(COVERAGE_DIR)/app/.coverage" $(PYTEST) $(PYTEST_FLAGS) $(CORE_PARALLEL) \
		--cov=backend --cov=frontend --cov-branch --cov-config="$(CURDIR)/pyproject.toml" \
		--cov-report=term-missing:skip-covered \
		--cov-report=xml:"$(CURDIR)/$(COVERAGE_DIR)/app/coverage.xml" \
		--cov-report=json:"$(CURDIR)/$(COVERAGE_DIR)/app/coverage.json" \
		--cov-report=html:"$(CURDIR)/$(COVERAGE_DIR)/app/htmlcov" || status=$$?; \
	(cd libs/docstruct && COVERAGE_FILE="$(CURDIR)/$(COVERAGE_DIR)/docstruct/.coverage" $(UV) run --extra dev --project "$(CURDIR)" python -m pytest \
		--cov=docstruct --cov-branch --cov-config="$(CURDIR)/pyproject.toml" \
		--cov-report=term-missing:skip-covered \
		--cov-report=xml:"$(CURDIR)/$(COVERAGE_DIR)/docstruct/coverage.xml" \
		--cov-report=json:"$(CURDIR)/$(COVERAGE_DIR)/docstruct/coverage.json" \
		--cov-report=html:"$(CURDIR)/$(COVERAGE_DIR)/docstruct/htmlcov") || status=$$?; \
	(cd libs/sdk && COVERAGE_FILE="$(CURDIR)/$(COVERAGE_DIR)/sdk/.coverage" $(UV) run --extra dev --project "$(CURDIR)" python -m pytest \
		--cov=acessilia_sdk --cov-branch --cov-config="$(CURDIR)/pyproject.toml" \
		--cov-report=term-missing:skip-covered \
		--cov-report=xml:"$(CURDIR)/$(COVERAGE_DIR)/sdk/coverage.xml" \
		--cov-report=json:"$(CURDIR)/$(COVERAGE_DIR)/sdk/coverage.json" \
		--cov-report=html:"$(CURDIR)/$(COVERAGE_DIR)/sdk/htmlcov") || status=$$?; \
	(cd libs/core && COVERAGE_FILE="$(CURDIR)/$(COVERAGE_DIR)/core/.coverage" $(UV) run --extra dev --project "$(CURDIR)" python -m pytest \
		--cov=acessilia_core --cov-branch --cov-config="$(CURDIR)/pyproject.toml" \
		--cov-report=term-missing:skip-covered \
		--cov-report=xml:"$(CURDIR)/$(COVERAGE_DIR)/core/coverage.xml" \
		--cov-report=json:"$(CURDIR)/$(COVERAGE_DIR)/core/coverage.json" \
		--cov-report=html:"$(CURDIR)/$(COVERAGE_DIR)/core/htmlcov") || status=$$?; \
	exit $$status

test-file:
	@if [ -z "$(F)" ]; then \
		printf '%s\n' 'usage: make test-file F=tests/test_example.py' >&2; \
		exit 2; \
	fi
	$(PYTEST) $(PYTEST_FLAGS) --durations=$(DURATIONS) "$(F)"

test-failed:
	$(UV) run python scripts/test_failed.py

test-all:
	@status=0; \
	$(PYTEST) $(PYTEST_FLAGS) $(CORE_PARALLEL) --durations=$(DURATIONS) || status=$$?; \
	(cd libs/docstruct && $(UV) run --extra dev pytest --durations=$(DURATIONS)) || status=$$?; \
	(cd libs/sdk && $(UV) run --extra dev pytest --durations=$(DURATIONS)) || status=$$?; \
	(cd libs/core && $(UV) run --extra dev pytest --durations=$(DURATIONS)) || status=$$?; \
	exit $$status
