"""
Load layer — writes transformed DataFrames to the warehouse and S3.

Supports:
  - MySQL (production warehouse)
  - SQLite (local dev)
  - AWS S3 (data lake, Parquet)
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
import logging
logger = logging.getLogger(__name__)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from psaksh_data_platform.config.settings import get_settings


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------

def get_engine(use_sqlite: bool = False) -> Engine:
    """
    Return a SQLAlchemy engine.
    - use_sqlite=True  → always SQLite (local dev)
    - use_sqlite=False → MySQL if ENV=production, else SQLite
    """
    settings = get_settings()
    if use_sqlite or settings.is_local:
        url = settings.db_url_local_sqlite
    else:
        url = settings.db_url
    return create_engine(url, echo=False, pool_pre_ping=True)


def load_to_db(
    df: pd.DataFrame,
    table_name: str,
    engine: Optional[Engine] = None,
    if_exists: Literal["replace", "append", "fail"] = "append",
    chunksize: int = 1000,
) -> int:
    """
    Load a DataFrame into a database table.

    Args:
        df:         DataFrame to load.
        table_name: Target table name.
        engine:     SQLAlchemy engine. Created from settings if not provided.
        if_exists:  Behaviour if table exists: 'append' (default), 'replace', 'fail'.
        chunksize:  Rows per INSERT batch.

    Returns:
        Number of rows loaded.
    """
    if engine is None:
        engine = get_engine()

    if df.empty:
        logger.warning(f"  Skipping load to '{table_name}' — DataFrame is empty")
        return 0

    df.to_sql(
        name=table_name,
        con=engine,
        if_exists=if_exists,
        index=False,
        chunksize=min(chunksize, 200) if engine.dialect.name == "sqlite" else chunksize,
        method="multi" if engine.dialect.name != "sqlite" else None,
    )
    logger.info(f"  Loaded {len(df):,} rows → {table_name} (if_exists={if_exists})")
    return len(df)


def upsert_to_db(
    df: pd.DataFrame,
    table_name: str,
    primary_key: str,
    engine: Optional[Engine] = None,
) -> int:
    """
    Upsert rows into a table using INSERT ... ON DUPLICATE KEY UPDATE (MySQL).
    Falls back to replace for SQLite.
    """
    if engine is None:
        engine = get_engine()

    dialect = engine.dialect.name
    if dialect == "sqlite":
        # SQLite: simple replace
        return load_to_db(df, table_name, engine, if_exists="replace")

    # MySQL upsert
    if df.empty:
        return 0

    cols = df.columns.tolist()
    placeholders = ", ".join([f":{c}" for c in cols])
    update_clause = ", ".join([f"`{c}` = VALUES(`{c}`)" for c in cols if c != primary_key])
    sql = (
        f"INSERT INTO `{table_name}` ({', '.join(f'`{c}`' for c in cols)}) "
        f"VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE {update_clause}"
    )

    with engine.begin() as conn:
        conn.execute(text(sql), df.to_dict(orient="records"))

    logger.info(f"  Upserted {len(df):,} rows → {table_name}")
    return len(df)


# ---------------------------------------------------------------------------
# S3 loading
# ---------------------------------------------------------------------------

def load_to_s3(
    df: pd.DataFrame,
    key: str,
    bucket: Optional[str] = None,
    fmt: Literal["parquet", "csv", "json"] = "parquet",
) -> str:
    """Upload a DataFrame to S3."""
    import boto3
    settings = get_settings()
    bucket = bucket or settings.s3_bucket

    buf = io.BytesIO()
    if fmt == "parquet":
        df.to_parquet(buf, index=False, engine="pyarrow")
    elif fmt == "csv":
        df.to_csv(buf, index=False)
    elif fmt == "json":
        df.to_json(buf, orient="records", lines=True)
    buf.seek(0)

    s3 = boto3.client("s3", region_name=settings.aws_region)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())

    uri = f"s3://{bucket}/{key}"
    logger.info(f"  Uploaded {len(df):,} rows → {uri}")
    return uri


def load_to_local(
    df: pd.DataFrame,
    path: str | Path,
    fmt: Literal["parquet", "csv", "json"] = "parquet",
) -> None:
    """Save a DataFrame to a local file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "parquet":
        df.to_parquet(path, index=False)
    elif fmt == "csv":
        df.to_csv(path, index=False)
    elif fmt == "json":
        df.to_json(path, orient="records", lines=True)

    logger.info(f"  Saved {len(df):,} rows → {path}")

