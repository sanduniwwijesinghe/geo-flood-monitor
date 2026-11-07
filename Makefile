.PHONY: install test lint fmt build local-up local-run local-down tf-plan deploy

install:
	pip install -e ".[dev]"

test:
	pytest -v

lint:
	ruff check . && ruff format --check .
	terraform -chdir=infra/terraform fmt -check -recursive
	helm lint deploy/helm/geo-flood-monitor

fmt:
	ruff format . && ruff check --fix .
	terraform -chdir=infra/terraform fmt -recursive

build:
	docker build -t geo-flood-monitor:dev .

local-up:
	docker compose up -d postgis titiler pushgateway prometheus

AOI ?= kelani-lower
local-run:
	docker compose run --rm pipeline run --aoi $(AOI)

local-down:
	docker compose down -v

tf-plan:
	terraform -chdir=infra/terraform init -backend-config=backend.hcl
	terraform -chdir=infra/terraform plan -out=tfplan

deploy:
	./deploy/bootstrap.sh
