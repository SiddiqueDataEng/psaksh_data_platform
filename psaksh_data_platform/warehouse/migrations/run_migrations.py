"""
Run all warehouse migrations — creates tables if they don't exist.
Safe to run repeatedly (idempotent).

Usage:
    python -m warehouse.migrations.run_migrations
"""

import sys
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine, inspect, text

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from psaksh_data_platform.config.settings import get_settings
from psaksh_data_platform.warehouse.models import Base


def run() -> None:
    settings = get_settings()
    engine = create_engine(settings.db_url, echo=False)

    logger.info(f"Connecting to: {settings.db_url.split('@')[-1]}")

    with engine.begin() as conn:
        # Verify connection
        conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")

    logger.info("Running migrations (create_all)...")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info(f"Tables in warehouse ({len(tables)}):")
    for t in sorted(tables):
        logger.info(f"  ✓ {t}")

    logger.info("Migrations complete.")


if __name__ == "__main__":
    run()

