install:
	poetry install

run:
	poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

test:
	poetry run pytest -q

typecheck:
	poetry run mypy .
