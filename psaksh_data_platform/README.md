# psaksh Data Platform

A cloud-ready, production-grade data engineering and analytics platform built for the Urban vs Rural (UIL) — Research, Analytics & Data Systems (psaksh) vertical.

## Architecture

```
psaksh_data_platform/
├── data_generator/         # Synthetic survey & health data generator
├── etl/                    # Extraction, transformation, loading pipelines
├── warehouse/              # Schema definitions and migrations
├── analytics/              # Analysis notebooks and scripts
├── dashboards/             # Streamlit dashboard app
├── automation/             # Playwright scrapers and scheduled jobs
├── geospatial/             # GeoPandas spatial processing
├── governance/             # PII handling, data dictionaries, codebooks
├── infra/                  # AWS CDK / Terraform cloud infrastructure
├── tests/                  # Unit and integration tests
├── config/                 # Environment configs
└── docker-compose.yml      # Local dev stack
```

## Quick Start

```bash
# 1. Clone and set up environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Start local stack (MySQL + MinIO S3-compatible)
docker-compose up -d

# 3. Initialize warehouse schema
python -m warehouse.migrations.run_migrations

# 4. Generate synthetic data
python -m data_generator.run --households 500 --submissions 5000

# 5. Run ETL pipeline
python -m etl.pipeline.run --env local

# 6. Launch dashboard
streamlit run dashboards/app.py
```

## Cloud Deployment (AWS)

```bash
cd infra/
terraform init
terraform apply -var-file=envs/staging.tfvars
```

## Environment Variables

Copy `.env.example` to `.env` and fill in values:

```
DB_HOST=localhost
DB_PORT=3306
DB_NAME=psaksh_warehouse
DB_USER=psaksh_user
DB_PASSWORD=...
S3_BUCKET=psaksh-data-lake
AWS_REGION=us-east-1
SURVEYCTO_SERVER=...
SURVEYCTO_USER=...
SURVEYCTO_PASSWORD=...
```
