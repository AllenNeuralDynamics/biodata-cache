"""Record-consistency checks cache table."""

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.record_consistency import (
    CHECK_DESCRIPTION,
    CHECK_IMPLEMENTATION_URL,
    CHECK_KEY,
    DOCDB_VERSION,
    V1_NAME_MISSING_V2_CHECK_KEY,
    V1_NAME_MISSING_V2_DOCDB_VERSION,
    DuplicateNameCheckSummary,
    V1NameMissingV2CheckSummary,
    evaluate_duplicate_names_v2,
    evaluate_v1_names_missing_v2,
)
from biodata_cache.utils import CacheLogMessage, setup_logging

TABLE_NAME = "record_consistency_checks"
MANIFEST_KEY = f"{TABLE_NAME}.manifest.json"
SOURCE_COLUMNS = ("_id", "name", "location")
V1_NAME_MISSING_V2_CHECK_DESCRIPTION = (
    "Fails every DocDB v1 record whose non-empty `name` has zero exact matches in DocDB v2."
)
V1_NAME_MISSING_V2_CHECK_IMPLEMENTATION_URL = (
    "https://github.com/AllenNeuralDynamics/biodata-cache/blob/bde9c5e/src/biodata_cache/record_consistency.py#L170"
)
RESULT_COLUMNS = (
    "check_key",
    "status",
    "docdb_id",
    "docdb_version",
    "name",
    "location",
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


def _duplicate_name_inputs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project cache records into the duplicate-name predicate contract."""
    return [{"_id": record["_id"], "name": record["name"]} for record in records]


def _add_source_context(
    rows: list[dict[str, Any]],
    records: list[Any],
) -> None:
    """Add display context without coupling the pure predicate to cache fields."""
    locations = {
        record.get("_id"): record.get("location")
        for record in records
        if isinstance(record, Mapping) and isinstance(record.get("_id"), str)
    }
    for row in rows:
        row["location"] = locations.get(row["docdb_id"])


def _fetch_v1_records() -> list[dict[str, Any]]:
    """Fetch the complete minimal v1 source population from DocDB."""
    from aind_data_access_api.document_db import MetadataDbClient

    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v1")
    return client.retrieve_docdb_records(
        filter_query={},
        projection={column: 1 for column in SOURCE_COLUMNS},
        sort={"_id": 1},
        limit=0,
    )


def _v1_source_records(records: list[Any]) -> list[Any]:
    """Normalize projected v1 records while preserving malformed inputs."""
    return [
        {column: _nullable_value(record.get(column)) for column in SOURCE_COLUMNS}
        if isinstance(record, Mapping)
        else record
        for record in records
    ]


def _duplicate_name_v2_manifest(summary: DuplicateNameCheckSummary) -> dict[str, Any]:
    """Build manifest accounting for the v2 duplicate-name check."""
    return {
        "check_key": CHECK_KEY,
        "description": CHECK_DESCRIPTION,
        "implementation_url": CHECK_IMPLEMENTATION_URL,
        "docdb_version": DOCDB_VERSION,
        "candidate_count": summary.candidate_count,
        "processed_count": summary.processed_count,
        "skipped_count": summary.skipped_count,
        "parse_failure_count": summary.parse_failure_count,
        "passed_count": summary.processed_count - summary.failed_count,
        "failed_count": summary.failed_count,
        "unknown_count": 0,
        "duplicate_group_count": summary.duplicate_group_count,
    }


def _v1_name_missing_v2_manifest(summary: V1NameMissingV2CheckSummary) -> dict[str, Any]:
    """Build manifest accounting for the v1-name coverage check."""
    return {
        "check_key": V1_NAME_MISSING_V2_CHECK_KEY,
        "description": V1_NAME_MISSING_V2_CHECK_DESCRIPTION,
        "implementation_url": V1_NAME_MISSING_V2_CHECK_IMPLEMENTATION_URL,
        "docdb_version": V1_NAME_MISSING_V2_DOCDB_VERSION,
        "candidate_count": summary.candidate_count,
        "processed_count": summary.processed_count,
        "skipped_count": summary.skipped_count,
        "parse_failure_count": summary.parse_failure_count,
        "passed_count": summary.processed_count - summary.failed_count,
        "failed_count": summary.failed_count,
        "unknown_count": 0,
    }


@registry.register_table(registry.NAMES["record_consistency_checks"])
def record_consistency_checks(force_update: bool = False) -> pd.DataFrame:
    """Build all record-consistency checks from cached prerequisite tables.

    The first check detects exact duplicate names in cached v2 DocDB records.
    The second checks a complete projected v1 DocDB sweep for names absent from
    v2. The builder never contacts S3 or Code Ocean. ``asset_basics`` must already
    have been built by the prerequisite sync job. A failed or malformed source
    sweep raises before writing data, preserving the previous result.

    Args:
        force_update: If True, rebuild from current ``asset_basics`` and DocDB v1.

    Returns:
        Complete check results, including passing rows.

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
            message="Updating record-consistency checks from asset_basics and DocDB v1",
        ).to_json()
    )
    source_records = _asset_basics_records(source)
    duplicate_rows, duplicate_summary = evaluate_duplicate_names_v2(_duplicate_name_inputs(source_records))
    _add_source_context(duplicate_rows, source_records)
    if not duplicate_summary.is_complete:
        raise ValueError(
            f"Cannot publish incomplete v2 duplicate-name flags: {duplicate_summary.parse_failure_count} parse failures"
        )

    v1_source_records = _v1_source_records(_fetch_v1_records())
    v2_names = {row["name"] for row in duplicate_rows}
    v1_rows, v1_summary = evaluate_v1_names_missing_v2(v1_source_records, v2_names)
    _add_source_context(v1_rows, v1_source_records)
    if not v1_summary.is_complete:
        raise ValueError(
            f"Cannot publish incomplete v1-name coverage flags: {v1_summary.parse_failure_count} parse failures"
        )

    rows = sorted(
        [*duplicate_rows, *v1_rows],
        key=lambda row: (row["check_key"], row["name"], row["docdb_id"]),
    )

    run_id = uuid4().hex
    checked_at = datetime.now(timezone.utc).isoformat()
    result = pd.DataFrame.from_records(rows, columns=RESULT_COLUMNS)
    result.insert(0, "checked_at", checked_at)
    result.insert(0, "run_id", run_id)

    check_manifests = [
        _duplicate_name_v2_manifest(duplicate_summary),
        _v1_name_missing_v2_manifest(v1_summary),
    ]
    manifest = {
        "complete": True,
        "run_id": run_id,
        "checked_at": checked_at,
        "table": TABLE_NAME,
        "check_count": len(check_manifests),
        "checks": check_manifests,
        "passed_count": sum(check["passed_count"] for check in check_manifests),
        "failed_count": sum(check["failed_count"] for check in check_manifests),
        "unknown_count": sum(check["unknown_count"] for check in check_manifests),
        "row_count": len(result),
    }

    # Write data before its completion manifest. A manifest is never published
    # for a failed classification or a failed data write.
    registry.BACKEND.write(TABLE_NAME, result)
    registry.BACKEND.put_json(MANIFEST_KEY, json.dumps(manifest, sort_keys=True))
    return result


def record_consistency_checks_columns() -> list[Column]:
    """Return registry metadata for the record-consistency checks table."""
    return [
        Column(name="run_id", description="Unique identifier for this consistency-check run"),
        Column(name="checked_at", description="UTC timestamp when this row was evaluated"),
        Column(name="check_key", description="Stable check identifier"),
        Column(name="status", description="Check result: pass, fail, or unknown"),
        Column(name="docdb_id", description="DocDB record ID"),
        Column(name="docdb_version", description="DocDB metadata version checked"),
        Column(name="name", description="Exact DocDB asset name evaluated"),
        Column(name="location", description="S3 location from the source DocDB record, when available"),
    ]
