"""Per-asset modality and stage QC statuses from DocDB."""

import logging
from datetime import datetime, timezone

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

QC_STATUS_FILTER = {"quality_control.status": {"$exists": True}}
QC_STATUS_FETCH_BATCH_SIZE = 50
_STATUS_COLUMN_NAMES: tuple[str, ...] = ()


def _metric_status_keys(quality_control: dict) -> set[str]:
    """Return the modality and stage keys represented by QC metrics."""
    keys = set()
    metrics = quality_control.get("metrics") or []
    if not isinstance(metrics, list):
        return keys

    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        modality = metric.get("modality")
        if isinstance(modality, dict):
            modality = modality.get("abbreviation")
        if isinstance(modality, str) and modality:
            keys.add(modality)
        stage = metric.get("stage")
        if isinstance(stage, str) and stage:
            keys.add(stage)
    return keys


def _status_row(record: dict) -> dict | None:
    """Build one row with only the asset's modality and stage statuses."""
    name = record.get("name")
    if not name:
        return None

    quality_control = record.get("quality_control") or {}
    statuses = quality_control.get("status") or {}
    if not isinstance(statuses, dict):
        statuses = {}
    keys = _metric_status_keys(quality_control)
    return {"name": name, **{key: statuses.get(key) for key in keys}}


def _record_version(record: dict) -> tuple[datetime, str]:
    """Return a stable ordering for duplicate records representing one asset."""
    modified = record.get("_last_modified")
    try:
        timestamp = datetime.fromisoformat(modified.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        timestamp = datetime.min.replace(tzinfo=timezone.utc)
    return timestamp, str(record.get("_id") or "")


def _fetch_qc_status() -> pd.DataFrame:
    """Fetch all QC status summaries from DocDB without reading other cache tables."""
    setup_logging()
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["qc_status"],
            message="Fetching QC status assets",
        ).to_json()
    )

    from aind_data_access_api.document_db import MetadataDbClient

    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
    index_records = client.retrieve_docdb_records(
        filter_query=QC_STATUS_FILTER,
        projection={"_id": 1, "name": 1},
        limit=0,
    )
    record_ids = [record["_id"] for record in index_records if record.get("_id") is not None]
    rows_by_name = {}

    projection = {
        "_id": 1,
        "_last_modified": 1,
        "name": 1,
        "quality_control.status": 1,
        "quality_control.metrics.modality": 1,
        "quality_control.metrics.stage": 1,
    }
    for start in range(0, len(record_ids), QC_STATUS_FETCH_BATCH_SIZE):
        batch_ids = record_ids[start : start + QC_STATUS_FETCH_BATCH_SIZE]
        records = client.retrieve_docdb_records(
            filter_query={"_id": {"$in": batch_ids}},
            projection=projection,
            limit=len(batch_ids),
        )
        for record in records:
            row = _status_row(record)
            if row is not None:
                version = _record_version(record)
                current = rows_by_name.get(row["name"])
                if current is None or version > current[0]:
                    rows_by_name[row["name"]] = (version, row)
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc_status"],
                message=f"Fetched {min(start + len(batch_ids), len(record_ids))}/{len(record_ids)} QC assets",
            ).to_json()
        )

    rows = [rows_by_name[name][1] for name in sorted(rows_by_name)]
    status_columns = tuple(
        sorted({key for row in rows for key in row if key != "name"}, key=lambda key: (key.casefold(), key))
    )
    global _STATUS_COLUMN_NAMES
    _STATUS_COLUMN_NAMES = status_columns
    df = pd.DataFrame.from_records(rows, columns=["name", *status_columns])
    registry.BACKEND.write(registry.NAMES["qc_status"], df)
    return df


@registry.register_table(registry.NAMES["qc_status"])
def qc_status(force_update: bool = False) -> pd.DataFrame:
    """Return one row per QC-bearing asset and modality/stage status columns."""
    global _STATUS_COLUMN_NAMES
    if force_update:
        return _fetch_qc_status()

    df = registry.BACKEND.read(registry.NAMES["qc_status"])
    if df.empty:
        raise ValueError("Cache is empty. Use force_update=True to fetch QC statuses from DocDB.")
    _STATUS_COLUMN_NAMES = tuple(column for column in df.columns if column != "name")
    return df


def qc_status_columns() -> list[Column]:
    """Return the registry columns discovered from the most recent QC status build."""
    return [
        Column(name="name", description="Asset name, joinable with asset_basics.name"),
        *[
            Column(name=key, description=f"Aggregated QC status for modality or stage {key!r}")
            for key in _STATUS_COLUMN_NAMES
        ],
    ]
