.PHONY: up down logs py-dev rs-dev proto test lint

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f --tail=200

py-dev:
	cd services/api-py && uv sync && uv run uvicorn app.main:app --reload --port 8000

rs-dev:
	cd services/ingest-rs && cargo run --release

proto:
	@mkdir -p services/api-py/app/providers/stockbit/generated
	@mkdir -p services/ingest-rs/proto
	cp shared/proto/datafeed.proto services/ingest-rs/proto/datafeed.proto
	cd services/api-py && uv run python -m grpc_tools.protoc -I../../shared/proto --python_out=app/providers/stockbit/generated ../../shared/proto/datafeed.proto && echo "proto py OK"
	cd services/ingest-rs && cargo build && echo "proto rs OK"

lint:
	cd services/api-py && uv run ruff check . && uv run ruff format --check . && uv run pyright
	cd services/ingest-rs && cargo fmt --check && cargo clippy -- -D warnings

test:
	cd services/api-py && uv run pytest -q
	cd services/ingest-rs && cargo test -- --nocapture
