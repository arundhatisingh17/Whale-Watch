# Override the interpreter if your default python3 lacks the dependencies, e.g.
#   make install PYTHON=/Users/induranasingh/anaconda3/bin/python
PYTHON ?= python3

.PHONY: help install env seed watch serve test clean

help:
	@echo "WhaleWatch - available targets:"
	@echo "  make install   Install Python dependencies"
	@echo "  make env       Create .env from .env.example (then add your Alchemy key)"
	@echo "  make seed      Backfill the 20 most recent whale transfers"
	@echo "  make watch     Run the watcher (writes new transfers to the database)"
	@echo "  make serve     Run the dashboard at http://localhost:5001"
	@echo "  make test      Run the test suite"
	@echo "  make clean     Delete the local SQLite database files"
	@echo ""
	@echo "Set PYTHON=<path> to choose the interpreter (default: python3)."

install:
	$(PYTHON) -m pip install -r requirements.txt

env:
	@if [ -f .env ]; then \
		echo ".env already exists, leaving it untouched."; \
	else \
		cp .env.example .env; \
		echo "Created .env from .env.example - now open it and add your Alchemy URL."; \
	fi

seed:
	$(PYTHON) seed.py

watch:
	$(PYTHON) watcher.py

serve:
	$(PYTHON) app.py

test:
	$(PYTHON) -m pytest tests/ -q

clean:
	rm -f transactions transactions-wal transactions-shm
