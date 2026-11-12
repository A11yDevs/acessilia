# Local test entry points; see docs/testing.md for the workflow.
#
# `test-all` runs the core suite with four workers after the isolation fixes
# tracked by #448 (PR 2); docstruct and SDK stay sequential because they are
# fast. Use `uv run pytest ...` directly for anything these targets do not cover.

UV ?= uv
PYTEST ?= $(UV) run pytest
PYTEST_FLAGS ?= -m "not e2e"
CORE_JOBS ?= 4
CORE_DIST ?= worksteal
CORE_PARALLEL ?= -n $(CORE_JOBS) --dist $(CORE_DIST)
DURATIONS ?= 25

.DEFAULT_GOAL := help

.PHONY: help test-file test-failed test-all

help:
	@printf '%s\n' \
		'make test-file F=tests/test_example.py  run one file or node id' \
		'make test-failed                        rerun the tests that failed last time' \
		'make test-all                           run the core (4 workers), docstruct and SDK suites'

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
	exit $$status
