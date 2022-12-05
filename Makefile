.DEFAULT_GOAL := all
sources = pydantic_settings tests

.PHONY: install
install:
	python -m pip install -U pip
	pip install -r requirements/all.txt
	pip install -e .

.PHONY: format
format:
	pyupgrade --py37-plus --exit-zero-even-if-changed `find $(sources) -name "*.py" -type f`
	isort $(sources)
	black $(sources)

.PHONY: lint
lint:
	flake8 $(sources)
	isort $(sources) --check-only --df
	black $(sources) --check --diff

.PHONY: mypy
mypy:
	mypy pydantic_settings

.PHONY: test
test:
	coverage run -m pytest --durations=10

.PHONY: testcov
testcov: test
	@echo "building coverage html"
	@coverage html

.PHONY: all
all: lint mypy testcov
