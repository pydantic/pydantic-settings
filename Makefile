.DEFAULT_GOAL := all
sources = pydantic_settings tests

.PHONY: install
install:
	uv sync --all-extras --all-groups

.PHONY: refresh-lockfiles
refresh-lockfiles:
	@echo "Updating uv.lock file"
	uv lock -U

.PHONY: format
format:
	uv run ruff check --fix $(sources)
	uv run ruff format $(sources)

.PHONY: lint
lint:
	uv run ruff check $(sources)
	uv run ruff format --check $(sources)

.PHONY: mypy
mypy:
	uv run mypy pydantic_settings

.PHONY: test
test:
	uv run coverage run -m pytest --durations=10

.PHONY: testcov
testcov: test
	@echo "building coverage html"
	@uv run coverage html

.PHONY: all
all: lint mypy testcov
