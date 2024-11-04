"""
Extraction layer — pulls data from source systems into the raw zone.

Sources:
  - Local CSV/Parquet files (generated data or SurveyCTO exports)
  - SurveyCTO REST API
  - AWS S3 raw zone
  - MySQL source tables
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import logging
logger = logging.getLogger(__name__)
from requests.auth import HTTPDigestAuth

from psaksh_data_platform.config.settings import get_settings


# ---------------------------------------------------------------------------
# Local file extraction
# ---------------------------------------------------------------------------

def extract_from_file(path: str | Path, fmt: Optional[str] = None) -> pd.DataFrame:
    """
    Load a CSV, Parquet, or JSON-lines file into a DataFrame.
    Format is inferred from extension if not specified.
    """
    path = Path(path)
    fmt = fmt or path.suffix.lstrip(".")

    logger.info(f"Extracting from file: {path}")
    if fmt == "csv":
        return pd.read_csv(path, low_memory=False)
    elif fmt == "parquet":
        return pd.read_parquet(path)
    elif fmt in ("json", "jsonl"):
        return pd.read_json(path, lines=True)
    else:
        raise ValueError(f"Unsupported format: {fmt}")


def extract_all_raw(raw_dir: str | Path = "data/raw") -> dict[str, pd.DataFrame]:
    """Load all raw data files from a directory into a dict of DataFrames."""
    raw_dir = Path(raw_dir)
    datasets: dict[str, pd.DataFrame] = {}

    for f in sorted(raw_dir.glob("*")):
        if f.suffix in (".csv", ".parquet", ".json"):
            name = f.stem
            datasets[name] = extract_from_file(f)
            logger.info(f"  Loaded '{name}': {len(datasets[name]):,} rows")

    return datasets


# ---------------------------------------------------------------------------
# SurveyCTO API extraction
# ---------------------------------------------------------------------------

def extract_from_surveycto(
    form_id: str,
    since_date: Optional[str] = None,
) -> pd.DataFrame:
    """
    Pull submissions from the SurveyCTO REST API.

    Args:
        form_id:    SurveyCTO form ID string.
        since_date: ISO date string (YYYY-MM-DD) to pull only new submissions.

    Returns:
        DataFrame of raw submissions.
    """
    settings = get_settings()

    if not settings.surveycto_server:
        raise EnvironmentError("SURVEYCTO_SERVER not configured.")

    url = f"{settings.surveycto_server}/api/v2/forms/data/wide/json/{form_id}"
    params: dict = {}
    if since_date:
        params["date"] = since_date

    logger.info(f"Pulling SurveyCTO form '{form_id}' since {since_date or 'beginning'}...")
    response = requests.get(
        url,
        params=params,
        auth=HTTPDigestAuth(settings.surveycto_user, settings.surveycto_password),
        timeout=120,
    )
    response.raise_for_status()

    data = response.json()
    df = pd.DataFrame(data)
    logger.info(f"  Received {len(df):,} submissions for form '{form_id}'")
    return df


# ---------------------------------------------------------------------------
# S3 extraction
# ---------------------------------------------------------------------------

def extract_from_s3(
    key: str,
    bucket: Optional[str] = None,
    fmt: Optional[str] = None,
) -> pd.DataFrame:
    """Download a file from S3 and return as a DataFrame."""
    import boto3
    settings = get_settings()
    bucket = bucket or settings.s3_bucket
    fmt = fmt or Path(key).suffix.lstrip(".")

    logger.info(f"Extracting from s3://{bucket}/{key}")
    s3 = boto3.client("s3", region_name=settings.aws_region)
    obj = s3.get_object(Bucket=bucket, Key=key)
    body = obj["Body"].read()

    if fmt == "csv":
        return pd.read_csv(io.BytesIO(body), low_memory=False)
    elif fmt == "parquet":
        return pd.read_parquet(io.BytesIO(body))
    elif fmt in ("json", "jsonl"):
        return pd.read_json(io.BytesIO(body), lines=True)
    else:
        raise ValueError(f"Unsupported S3 format: {fmt}")


def list_s3_keys(prefix: str, bucket: Optional[str] = None) -> list[str]:
    """List all object keys under a given S3 prefix."""
    import boto3
    settings = get_settings()
    bucket = bucket or settings.s3_bucket
    s3 = boto3.client("s3", region_name=settings.aws_region)

    paginator = s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])

    logger.info(f"Found {len(keys)} objects under s3://{bucket}/{prefix}")
    return keys

