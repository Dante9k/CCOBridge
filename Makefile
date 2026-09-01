.PHONY: bundle check format install install-online integration lifecycle lint privacy test usage users

install:
	sudo ./deploy/install.sh

install-online:
	sudo ./deploy/install.sh --online

bundle:
	./scripts/build-offline.sh

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

users:
	sudo /opt/ccobridge/users.sh list

usage:
	sudo /opt/ccobridge/usage.sh
