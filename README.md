# PSAKSH Data Platform

**Public Sector Analytics & Knowledge Systems Hub**  
Pakistan Public Health Surveillance — Medallion ETL Pipeline · Flask + Streamlit Dashboards · REST API

[![Live Demo](https://img.shields.io/badge/Live%20Demo-softcomputech.com-1a365d?style=for-the-badge&logo=flask)](https://softcomputech.com/publichealth)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=for-the-badge&logo=flask)](https://flask.palletsprojects.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35-FF4B4B?style=for-the-badge&logo=streamlit)](https://streamlit.io)

---

## 🌐 Live Application

| Interface | URL |
|-----------|-----|
| **Flask Dashboard** | https://softcomputech.com/publichealth |
| **Overview** | https://softcomputech.com/publichealth/ |
| **Nutrition Analytics** | https://softcomputech.com/publichealth/nutrition |
| **Maternal Health** | https://softcomputech.com/publichealth/maternal |
| **Field Operations** | https://softcomputech.com/publichealth/field |
| **Facilities** | https://softcomputech.com/publichealth/facilities |
| **Data Pipeline** | https://softcomputech.com/publichealth/data-pipeline |
| **REST API** | https://softcomputech.com/publichealth/api/v1/ |
| **KPIs JSON** | https://softcomputech.com/publichealth/api/v1/kpis |

---

## 📊 Project Overview

PSAKSH is a production-grade data engineering and analytics platform built for Pakistan's public health surveillance programme. It processes survey data from **4 provinces**, **36 districts**, and **180 union councils**, covering child nutrition, maternal health, and facility readiness.

### Key Metrics (Live Data)
| Indicator | Value |
|-----------|-------|
| Households enrolled | 34,250+ |
| Children measured | 18,978 |
| Stunting rate | ~43% |
| Wasting rate | ~13% |
| ANC 4+ coverage | ~54% |
| Skilled delivery | ~71% |
| Districts covered | 36 |
| Survey rounds | 4 |

---

## 🏗️ Architecture — Medallion Pattern

```
Raw Sources (heterogeneous)
  ├── 2020: Paper surveys → CSV
  ├── 2021: HMIS system → JSON
  ├── 2022: Hadoop pipeline → Parquet
  └── Current: MySQL DB exports → Parquet
         │
         ▼
    ┌─────────┐
    │ BRONZE  │  Exact copy + lineage metadata
    │         │  _source_file, _source_era, _ingested_at
    └────┬────┘
         │  Schema evolution (50+ column renames)
         │  Bilingual normalisation (Urdu/English)
         │  GPS validation, deduplication, CDC tagging
         ▼
    ┌─────────┐
    │ SILVER  │  Cleaned, validated, CDC-tagged
    │         │  _cdc_op (INSERT/UPDATE/UPSERT), _cdc_ts
    └────┬────┘
         │  SCD Type 2 dimensions
         │  Windowed KPI aggregations
         │  Fact table joins (province, ses_tier, visit_round)
         ▼
    ┌─────────┐
    │  GOLD   │  Analysis-ready facts, dims, KPIs
    │         │  fct_child_nutrition, fct_maternal_health
    └────┬────┘  rpt_district_summary, dim_district (SCD2)
         │
    ┌────┴──────────────────────────────┐
    │  Flask Dashboard  │  Streamlit    │
    │  REST API (v1)    │  Power BI     │
    │  Tableau WDC      │  Glossary     │
    └───────────────────────────────────┘
```

### Data Engineering Techniques
| Technique | Implementation |
|-----------|---------------|
| **Full Load** | Initial historical data (2020–2022) |
| **Incremental Load** | MD5 checksum-based change detection |
| **CDC** | INSERT/UPDATE/UPSERT tagging per Silver record |
| **SCD Type 2** | `dim_district`, `dim_facility` with effective dates |
| **Delta Log** | `pipeline_state.json` — watermarks, checksums, run history |
| **Schema Evolution** | 50+ column renames across legacy years |
| **Data Lineage** | `_source_file`, `_source_era`, `_ingested_at`, `_cdc_ts` |
| **DQ Injection** | Bilingual values, GPS errors, duplicates, outliers |
| **Windowing** | Monthly/quarterly/annual KPI aggregations |
| **Upsert/Merge** | Gold layer merge on primary key |

---

## 📁 Project Structure

```
psaksh_data_platform/
├── analytics/              # Prevalence, trend, double burden, field monitoring
├── config/                 # Pydantic-settings environment config
├── dashboards/             # Streamlit interactive dashboard
│   └── app.py              # 9 pages: Overview, Nutrition, Maternal, Field, ...
├── data_generator/         # Synthetic Pakistan-wide survey data
│   ├── config.py           # 4 provinces, 36 districts, 180 UCs, 108 facilities
│   ├── generators.py       # Households, visits, facilities, backcheck
│   └── historical.py       # 2020 CSV, 2021 JSON, 2022 Parquet legacy formats
├── deploy/                 # cPanel deployment scripts
│   ├── deploy_ftp.py       # FTP upload with correct path handling
│   ├── quickfix.sh         # Server: regenerate data + run ETL
│   └── setup.sh            # Full server setup
├── etl/
│   ├── medallion.py        # Bronze → Silver → Gold pipeline
│   ├── transform.py        # Domain-specific DQ transforms
│   ├── extract.py          # Source extraction helpers
│   └── pipeline/run.py     # CLI orchestrator
├── geospatial/             # GeoPandas spatial analysis
├── governance/             # PII handler, data dictionary
├── tests/                  # 82 unit tests (pytest)
│   ├── test_generators.py
│   ├── test_transform.py
│   ├── test_analytics.py
│   ├── test_webapp.py
│   └── test_streamlit_app.py
├── warehouse/              # SQLAlchemy models, Alembic migrations
└── webapp/
    ├── app.py              # Flask routes (Overview, Nutrition, Maternal, ...)
    ├── api/routes.py       # REST API v1 — Power BI / Tableau / JSON
    └── templates/          # Jinja2 HTML templates (10 pages)
```

---

## 🚀 Quick Start (Local)

```bash
# 1. Clone and set up environment
git clone https://github.com/SiddiqueDataEng/psaksh_data_platform.git
cd psaksh_data_platform
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r psaksh_data_platform/requirements.txt

# 2. Generate synthetic data
python -m psaksh_data_platform.data_generator.run --households 500 --rounds 4

# 3. Run ETL pipeline (Bronze → Silver → Gold)
python -m psaksh_data_platform.etl.pipeline.run

# 4. Launch Flask dashboard
set ENV=local
python -m flask --app psaksh_data_platform.webapp.app run --port 5000
# Open: http://localhost:5000/publichealth/

# 5. Launch Streamlit dashboard
python -m streamlit run psaksh_data_platform/dashboards/app.py
# Open: http://localhost:8501
```

---

## 📡 REST API

Base URL: `https://softcomputech.com/publichealth/api/v1/`

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/` | API discovery — all endpoints |
| `GET /api/v1/kpis` | National KPI summary (Power BI ready) |
| `GET /api/v1/child-nutrition` | Child anthropometry fact table |
| `GET /api/v1/maternal-health` | Maternal health fact table |
| `GET /api/v1/district-summary` | Pre-aggregated district KPIs |
| `GET /api/v1/facilities` | Facility readiness assessments |
| `GET /api/v1/households` | Enrolled households (PII removed) |
| `GET /api/v1/pipeline-status` | Medallion layer statistics |
| `GET /api/v1/tableau/<dataset>` | Tableau WDC compatible endpoint |

**Filtering:** `?district=Lahore&visit_round=2`  
**Pagination:** `?limit=1000&offset=0`  
**Field selection:** `?fields=district,stunting_rate,visit_round`

**Power BI:** Get Data → Web → paste any endpoint URL  
**Tableau:** Web Data Connector → `/api/v1/tableau/child-nutrition`

---

## 🧪 Tests

```bash
# Run all 82 tests
python -m pytest psaksh_data_platform/tests/ -v

# Run specific suites
python -m pytest psaksh_data_platform/tests/test_generators.py   # Data generators
python -m pytest psaksh_data_platform/tests/test_transform.py    # ETL transforms
python -m pytest psaksh_data_platform/tests/test_analytics.py    # Analytics layer
python -m pytest psaksh_data_platform/tests/test_webapp.py       # Flask routes
python -m pytest psaksh_data_platform/tests/test_streamlit_app.py # Streamlit
```

---

## 🌍 Coverage

| Province | Districts | Union Councils | Facilities |
|----------|-----------|----------------|------------|
| Punjab | 9 | 45 | 27 |
| Sindh | 9 | 45 | 27 |
| KPK | 9 | 45 | 27 |
| Balochistan | 9 | 45 | 27 |
| **Total** | **36** | **180** | **108** |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Web Framework | Flask 3.0 + Passenger WSGI |
| Dashboard | Streamlit 1.35 |
| Data | Pandas 2.2, PyArrow, Parquet |
| Visualisation | Plotly 5.22 |
| ETL | Custom Medallion pipeline |
| Database | MySQL (production), SQLite (local) |
| ORM | SQLAlchemy 2.0 |
| Config | Pydantic-settings |
| Testing | pytest 8.2 (82 tests) |
| Deployment | cPanel, Passenger, FTP |
| Geospatial | GeoPandas, Shapely, Folium |

---

## 👥 Team

| Contributor | Role |
|-------------|------|
| **SiddiqueDataEng** | Lead Data Engineer — Architecture, ETL, Flask, API |
| **Farjad-SCT** | Data Engineer — Gold layer, SCD2, analytics |
| **Saira-SCT** | Analytics Engineer — Prevalence, Streamlit, testing |
| **Usama-SCT** | Frontend Engineer — Templates, Streamlit pages |
| **Irfan-SCT** | Backend Engineer — API, deployment, governance |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for the Urban Impact Lab (UIL) — Research, Analytics & Data Systems (RADS) vertical.*  
*MeriSehat and AapiVerse public health programmes, Pakistan.*
