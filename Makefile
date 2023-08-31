.DEFAULT_GOAL := all
sources = pydantic_settings tests

.PHONY: install
install:
	pdm install -d

.PHONY: format
format:
	pdm run black $(sources)
	pdm run ruff --fix $(sources)

.PHONY: lint
lint:
	pdm run ruff $(sources)
	pdm run black $(sources) --check --diff

.PHONY: mypy
mypy:
	pdm run mypy pydantic_settings

.PHONY: test
test:
	pdm run coverage run -m pytest --durations=10

.PHONY: testcov
testcov: test
	@echo "building coverage html"
	@pdm run coverage html

.PHONY: all
all: lint mypy testcov
