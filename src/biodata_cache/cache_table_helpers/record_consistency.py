"""V2 record-consistency cache table."""

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.record_consistency import (
    CHECK_CLASS,
    CHECK_KEY,
    DOCDB_VERSION,
    evaluate_duplicate_names_v2,
)
from biodata_cache.utils import CacheLogMessage, setup_logging

TABLE_NAME = "record_consistency_flags_v2"
MANIFEST_KEY = f"{TABLE_NAME}.manifest.json"
SOURCE_COLUMNS = ("_id", "name", "location")
RESULT_COLUMNS = (
    "check_key",
    "check_class",
    "docdb_version",
    "docdb_id",
    "name",
    "location",
    "status",
    "duplicate_group_count",
    "peer_docdb_ids",
    "peer_names",
    "reason",
    "error_type",
)
TABLE_COLUMNS = ("run_id", "checked_at", *RESULT_COLUMNS)


def _nullable_value(value: Any) -> Any:
    """Convert pandas scalar nulls to ``None`` for the pure predicate."""
    if value is None:
        return None
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def _asset_basics_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Project the v2 asset-basics cache into the pure check's input contract."""
    required = {"_id", "name"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"asset_basics is missing required columns: {missing}")

    return [
        {column: _nullable_value(record.get(column)) for column in SOURCE_COLUMNS}
        for record in df.to_dict(orient="records")
    ]


@registry.register_table(registry.NAMES["record_consistency_v2"])
def record_consistency_flags_v2(force_update: bool = False) -> pd.DataFrame:
    """Build v2 duplicate-name flags from the cached ``asset_basics`` table.

    The builder never contacts DocDB, S3, or Code Ocean. ``asset_basics`` must
    already have been built by the prerequisite sync job. A failed or malformed
    source sweep raises before writing data, preserving the previous result.

    Args:
        force_update: If True, rebuild from the current ``asset_basics`` cache.

    Returns:
        The complete flags table, including passing singleton rows.

    Raises:
        ValueError: If the prerequisite cache is missing, has an invalid schema,
            or contains records that cannot be classified completely.
    """
    cached = registry.BACKEND.read(TABLE_NAME)
    if not cached.empty and not force_update:
        return cached

    source = registry.BACKEND.read(registry.NAMES["basics"])
    if source.empty:
        raise ValueError("asset_basics cache is empty; run the asset_basics job first")

    setup_logging()
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=TABLE_NAME,
            message="Updating v2 duplicate-name flags from asset_basics",
        ).to_json()
    )
    rows, summary = evaluate_duplicate_names_v2(_asset_basics_records(source))
    if not summary.is_complete:
        raise ValueError(
            f"Cannot publish incomplete v2 duplicate-name flags: {summary.parse_failure_count} parse failures"
        )

    run_id = uuid4().hex
    checked_at = datetime.now(timezone.utc).isoformat()
    result = pd.DataFrame.from_records(rows, columns=RESULT_COLUMNS)
    result.insert(0, "checked_at", checked_at)
    result.insert(0, "run_id", run_id)

    manifest = {
        "complete": True,
        "run_id": run_id,
        "checked_at": checked_at,
        "table": TABLE_NAME,
        "check_key": CHECK_KEY,
        "check_class": CHECK_CLASS,
        "docdb_version": DOCDB_VERSION,
        "candidate_count": summary.candidate_count,
        "processed_count": summary.processed_count,
        "skipped_count": summary.skipped_count,
        "parse_failure_count": summary.parse_failure_count,
        "failed_count": summary.failed_count,
        "duplicate_group_count": summary.duplicate_group_count,
        "row_count": len(result),
    }

    # Write data before its completion manifest. A manifest is never published
    # for a failed classification or a failed data write.
    registry.BACKEND.write(TABLE_NAME, result)
    registry.BACKEND.put_json(MANIFEST_KEY, json.dumps(manifest, sort_keys=True))
    return result


def record_consistency_flags_v2_columns() -> list[Column]:
    """Return registry metadata for the v2 record-consistency table."""
    return [
        Column(name="run_id", description="Unique identifier for this consistency-check run"),
        Column(name="checked_at", description="UTC timestamp when this row was evaluated"),
        Column(name="check_key", description="Stable check identifier"),
        Column(name="check_class", description="Consistency taxonomy class"),
        Column(name="docdb_version", description="DocDB metadata version checked"),
        Column(name="docdb_id", description="DocDB record ID"),
        Column(name="name", description="Exact DocDB asset name used for duplicate grouping"),
        Column(name="location", description="S3 location from asset_basics, when available"),
        Column(name="status", description="Check result: pass or fail"),
        Column(name="duplicate_group_count", description="Number of v2 records sharing this exact name"),
        Column(name="peer_docdb_ids", description="Other v2 DocDB IDs in the duplicate-name group"),
        Column(name="peer_names", description="Names corresponding to peer_docdb_ids"),
        Column(name="reason", description="Human-readable reason for a failed check"),
        Column(name="error_type", description="Optional classification error type"),
    ]
