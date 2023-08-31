.DEFAULT_GOAL := all
sources = pydantic_settings tests

.PHONY: install ## Install dev dependencies
install:
	pdm install -d

.PHONY: format ## Format the code
format:
	pdm run black $(sources)
	pdm run ruff --fix $(sources)

.PHONY: lint ## Lint the code
lint:
	pdm run ruff $(sources)
	pdm run black $(sources) --check --diff

.PHONY: mypy ## Static type checking
mypy:
	pdm run mypy pydantic_settings

.PHONY: test ## Run the unit tests
test:
	pdm run coverage run -m pytest --durations=10

.PHONY: testcov ## Run the code coverage and generate a report
testcov: test
	@echo "building coverage html"
	@pdm run coverage html

.PHONY: help  ## Display this message
help:
	@grep -E \
		'^.PHONY: .*?## .*$$' $(MAKEFILE_LIST) | \
		sort | \
		awk 'BEGIN {FS = ".PHONY: |## "}; {printf "\033[36m%-19s\033[0m %s\n", $$2, $$3}'

.PHONY: all ## Execute commands lint, mypy and testcov
all: lint mypy testcov
