# VA Congressional Tracker — local orchestration
# Prefer ./bin/vact so PYTHONPATH/VACT_REPO_ROOT stay correct.

VACT := ./bin/vact
UV := uv
PYTEST := PYTHONPATH=src VACT_REPO_ROOT=$(CURDIR) .venv/bin/pytest

.PHONY: install ingest classify score deviations export-web test site social publish all dimensions contracts gaps

install:
	$(UV) sync
	@test -x .venv/bin/python || $(UV) venv
	$(UV) pip install -e .

ingest:
	$(VACT) incremental --lookback-days 7

classify:
	$(VACT) classify --new-only --no-llm

score:
	$(VACT) score --write

deviations:
	$(VACT) deviations

export-web:
	$(VACT) export-web

test:
	$(PYTEST) -q

contracts:
	$(VACT) contracts

dimensions:
	$(VACT) dimensions

gaps:
	$(VACT) gaps

site:
	$(VACT) site
	$(VACT) social

# Audit Sheets push is best-effort when credentials are present.
publish: site
	@if [ -n "$${VACT_SHEETS_CREDENTIALS:-}" ] && [ -n "$${VACT_SHEETS_ID:-}" ]; then \
		$(VACT) sheets push ; \
	else \
		echo "Skipping sheets push (set VACT_SHEETS_CREDENTIALS and VACT_SHEETS_ID)" ; \
	fi
	$(VACT) gaps

all: install ingest classify test publish
