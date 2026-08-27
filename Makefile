.PHONY: check format integration lifecycle lint privacy test

check: lint test privacy

lint:
	python3 -m ruff check .
	python3 -m ruff format --check .
	shellcheck client/*.sh deploy/*.sh scripts/build-offline.sh tests/*.sh

format:
	python3 -m ruff check --fix .
	python3 -m ruff format .

test:
	PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'

privacy:
	python3 scripts/check-public-release.py

integration:
	./tests/run-integration.sh

lifecycle:
	sudo ./tests/run-install-lifecycle.sh
