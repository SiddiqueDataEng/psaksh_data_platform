"""
ETL Pipeline State Manager — Watermark, CDC, and Delta Log tracking.

Implements real data engineering patterns:
  - Watermark tracking: last successful load timestamp per dataset
  - CDC log: change data capture operations (INSERT/UPDATE/DELETE)
  - Delta log: audit trail of every pipeline run (Delta Lake pattern)
  - Partition registry: tracks which year/month partitions exist
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

STATE_FILE = "pipeline_state.json"


def _load_state(state_dir: Path) -> dict:
    """Load pipeline state from JSON file."""
    path = state_dir / STATE_FILE
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "watermarks":   {},   # dataset -> last_loaded_at ISO string
        "run_history":  [],   # list of run summaries
        "partitions":   {},   # dataset -> list of partition keys
        "cdc_sequence": 0,    # monotonic CDC sequence number
    }


def _save_state(state: dict, state_dir: Path) -> None:
    """Persist pipeline state to JSON file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / STATE_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def get_watermark(state: dict, dataset: str) -> str | None:
    """Return the last successful load timestamp for a dataset."""
    return state.get("watermarks", {}).get(dataset)


def set_watermark(state: dict, dataset: str, ts: str) -> None:
    """Update the watermark for a dataset after successful load."""
    state.setdefault("watermarks", {})[dataset] = ts


def record_run(
    state: dict,
    run_id: str,
    datasets: dict[str, int],
    load_type: str,
    elapsed: float,
    status: str = "success",
) -> None:
    """Append a run summary to the run history (Delta Log pattern)."""
    state.setdefault("run_history", []).append({
        "run_id":    run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "load_type": load_type,
        "status":    status,
        "elapsed_s": round(elapsed, 2),
        "datasets":  datasets,
    })
    # Keep last 100 runs
    state["run_history"] = state["run_history"][-100:]


def add_cdc_columns(
    df: pd.DataFrame,
    operation: str = "INSERT",
    source: str = "",
    sequence: int = 0,
) -> pd.DataFrame:
    """
    Add CDC metadata columns to a DataFrame.

    _cdc_op:       INSERT | UPDATE | DELETE
    _cdc_ts:       timestamp of the change
    _cdc_source:   source system identifier
    _cdc_seq:      monotonic sequence number for ordering
    """
    now = datetime.now(timezone.utc).isoformat()
    df = df.copy()
    df["_cdc_op"]     = operation
    df["_cdc_ts"]     = now
    df["_cdc_source"] = source
    df["_cdc_seq"]    = range(sequence, sequence + len(df))
    return df


def add_lineage_columns(
    df: pd.DataFrame,
    source_file: str,
    source_era: str,
    source_type: str,
    ingested_at: str,
) -> pd.DataFrame:
    """Add data lineage tracking columns."""
    df = df.copy()
    df["_source_file"] = source_file
    df["_source_era"]  = source_era
    df["_source_type"] = source_type
    df["_ingested_at"] = ingested_at
    df["_layer"]       = "bronze"
    return df


def write_delta_partition(
    df: pd.DataFrame,
    base_dir: Path,
    dataset: str,
    partition_col: str = "_ingested_at",
) -> list[str]:
    """
    Write data in Delta Lake-style partitions (year=YYYY/month=MM/).
    Returns list of partition paths written.
    """
    if df.empty:
        return []

    partitions_written = []
    base_dir.mkdir(parents=True, exist_ok=True)

    try:
        ts_col = pd.to_datetime(df[partition_col], errors="coerce")
        df = df.copy()
        df["_part_year"]  = ts_col.dt.year.fillna(2024).astype(int)
        df["_part_month"] = ts_col.dt.month.fillna(1).astype(int)

        for (year, month), group in df.groupby(["_part_year", "_part_month"]):
            part_dir = base_dir / dataset / f"year={year}" / f"month={month:02d}"
            part_dir.mkdir(parents=True, exist_ok=True)
            out = part_dir / "data.parquet"
            group_clean = group.drop(columns=["_part_year", "_part_month"])
            try:
                group_clean.to_parquet(out, index=False)
            except Exception:
                group_clean.to_csv(out.with_suffix(".csv"), index=False)
            partitions_written.append(str(out.relative_to(base_dir)))

    except Exception as e:
        logger.warning(f"  Delta partition write failed for {dataset}: {e}")
        # Fallback: write as single file
        out = base_dir / dataset / "data.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            df.to_parquet(out, index=False)
        except Exception:
            df.to_csv(out.with_suffix(".csv"), index=False)
        partitions_written.append(str(out.relative_to(base_dir)))

    return partitions_written


def apply_scd2(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    pk_col: str,
    track_cols: list[str],
) -> pd.DataFrame:
    """
    Apply SCD Type 2 (Slowly Changing Dimension) logic.

    For each incoming record:
      - If PK is new: INSERT with effective_from=now, effective_to=NULL, is_current=True
      - If PK exists and tracked columns changed: expire old row, INSERT new row
      - If PK exists and no change: keep existing row unchanged

    Returns the merged dimension table with full history.
    """
    now = datetime.now(timezone.utc).isoformat()

    if existing.empty:
        incoming = incoming.copy()
        incoming["_scd_effective_from"] = now
        incoming["_scd_effective_to"]   = None
        incoming["_scd_is_current"]     = True
        incoming["_scd_version"]        = 1
        return incoming

    result_rows = []

    for _, new_row in incoming.iterrows():
        pk_val = new_row[pk_col]
        existing_current = existing[
            (existing[pk_col] == pk_val) &
            (existing.get("_scd_is_current", pd.Series([True] * len(existing))) == True)
        ]

        if existing_current.empty:
            # New record — INSERT
            row = new_row.to_dict()
            row["_scd_effective_from"] = now
            row["_scd_effective_to"]   = None
            row["_scd_is_current"]     = True
            row["_scd_version"]        = 1
            result_rows.append(row)
        else:
            old_row = existing_current.iloc[0]
            changed = any(
                str(new_row.get(c, "")) != str(old_row.get(c, ""))
                for c in track_cols if c in new_row.index
            )
            if changed:
                # Expire old row
                expired = old_row.to_dict()
                expired["_scd_effective_to"] = now
                expired["_scd_is_current"]   = False
                result_rows.append(expired)
                # Insert new version
                row = new_row.to_dict()
                row["_scd_effective_from"] = now
                row["_scd_effective_to"]   = None
                row["_scd_is_current"]     = True
                row["_scd_version"]        = int(old_row.get("_scd_version", 1)) + 1
                result_rows.append(row)
            else:
                # No change — keep existing
                result_rows.append(old_row.to_dict())

    # Add historical rows not in incoming
    if pk_col in existing.columns:
        incoming_pks = set(incoming[pk_col].tolist())
        historical = existing[~existing[pk_col].isin(incoming_pks)]
        result_rows.extend(historical.to_dict("records"))

    return pd.DataFrame(result_rows)


def merge_upsert(
    existing: pd.DataFrame,
    incoming: pd.DataFrame,
    pk_col: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Merge/upsert incoming records into existing dataset.
    Returns (merged_df, stats) where stats = {inserts, updates, unchanged}.
    """
    if existing.empty:
        return incoming.copy(), {"inserts": len(incoming), "updates": 0, "unchanged": 0}

    stats = {"inserts": 0, "updates": 0, "unchanged": 0}
    existing_map = {row[pk_col]: i for i, row in existing.iterrows()
                    if pk_col in existing.columns}

    result = existing.copy()
    new_rows = []

    for _, row in incoming.iterrows():
        pk_val = row.get(pk_col)
        if pk_val in existing_map:
            # Update existing
            result.loc[existing_map[pk_val]] = row
            stats["updates"] += 1
        else:
            new_rows.append(row.to_dict())
            stats["inserts"] += 1

    if new_rows:
        result = pd.concat([result, pd.DataFrame(new_rows)], ignore_index=True)

    stats["unchanged"] = len(existing) - stats["updates"]
    return result, stats
