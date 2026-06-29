"""Time to QC cache table: measures elapsed time from processing to QC completion."""

import logging
from datetime import datetime, timezone

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.asset_basics import asset_basics
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging


def _get_last_process_datetime(processing: dict) -> str | None:
    """Return the end_date_time of the last data process, or None if unavailable."""
    data_processes = processing.get("data_processes", []) or []
    if not data_processes:
        return None
    last = data_processes[-1]
    return last.get("end_date_time", last.get("start_date_time", None))


def _has_pending_status(status_dict: dict) -> bool:
    """Return True if any value in status_dict is 'Pending'."""
    return any(v == "Pending" for v in status_dict.values())


def _get_last_metric_timestamp(metrics: list) -> str | None:
    """Return the latest timestamp from the last status_history entry of each metric."""
    timestamps = []
    for metric in metrics:
        status_history = metric.get("status_history", []) or []
        if status_history:
            ts = status_history[-1].get("timestamp", None)
            if ts:
                timestamps.append(ts)
    if not timestamps:
        return None
    return max(timestamps)


def _get_qc_time(quality_control: dict) -> str | None:
    """Return the qc_time for a record.

    If any entry in the status dict is 'Pending', returns the current UTC
    datetime (QC is not yet complete). Otherwise, returns the latest timestamp
    from the last status_history entry across all metrics.
    """
    status_dict = quality_control.get("status", {}) or {}
    if isinstance(status_dict, dict) and status_dict and _has_pending_status(status_dict):
        return datetime.now(timezone.utc).isoformat()
    metrics = quality_control.get("metrics", []) or []
    return _get_last_metric_timestamp(metrics)


@registry.register_table(registry.NAMES["time_to_qc"])
def time_to_qc(force_update: bool = False) -> pd.DataFrame:
    """Fetch time-to-QC data for all derived assets with quality control records.

    Returns a DataFrame with columns: name, process_end_time, qc_time.
    Assets without a quality_control record are excluded.

    process_end_time is the end_date_time (or start_date_time if unavailable)
    of the last data process in the processing record.

    qc_time is the current UTC datetime if any QC status is 'Pending',
    otherwise the latest timestamp from metrics' status history.

    Args:
        force_update: If True, bypass cache and fetch fresh data from database.

    Returns:
        DataFrame with name, process_end_time, and qc_time columns.

    """
    df = registry.BACKEND.read(registry.NAMES["time_to_qc"])

    if df.empty and not force_update:
        logging.error(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["time_to_qc"],
                message="Cache is empty. Use force_update=True to fetch data from database.",
            ).to_json()
        )

    if force_update:
        df = _fetch_time_to_qc()

    return df


def _fetch_time_to_qc() -> pd.DataFrame:
    """Build time-to-QC DataFrame from DocDB for all derived assets."""
    setup_logging()
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["time_to_qc"],
            message="Updating cache",
        ).to_json()
    )

    basics_df = asset_basics()
    derived_df = basics_df[basics_df["data_level"] == "derived"]

    if derived_df.empty:
        df = pd.DataFrame(columns=["name", "process_end_time", "qc_time"])
        registry.BACKEND.write(registry.NAMES["time_to_qc"], df)
        return df

    asset_names = derived_df["name"].dropna().tolist()

    from aind_data_access_api.document_db import MetadataDbClient
    client = MetadataDbClient(
        host=registry.API_GATEWAY_HOST,
        version="v2",
    )

    rows = []
    batch_size = 50
    for i in range(0, len(asset_names), batch_size):
        batch = asset_names[i : i + batch_size]
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["time_to_qc"],
                message=f"Fetching batch {i // batch_size + 1}",
            ).to_json()
        )
        records = client.retrieve_docdb_records(
            filter_query={"name": {"$in": batch}},
            projection={"name": 1, "processing.data_processes": 1, "quality_control": 1},
            limit=0,
        )
        for record in records:
            quality_control = record.get("quality_control")
            if not quality_control:
                continue
            processing = record.get("processing", {}) or {}
            rows.append(
                {
                    "name": record.get("name", ""),
                    "process_end_time": _get_last_process_datetime(processing),
                    "qc_time": _get_qc_time(quality_control),
                }
            )

    df = pd.DataFrame(rows, columns=["name", "process_end_time", "qc_time"])
    registry.BACKEND.write(registry.NAMES["time_to_qc"], df)
    return df


def time_to_qc_columns() -> list[Column]:
    """Return time_to_qc cache table column definitions."""
    return [
        Column(name="name", description="Asset name, joinable with asset_basics.name"),
        Column(name="process_end_time", description="Datetime of the last data process completion"),
        Column(
            name="qc_time",
            description=(
                "Current UTC datetime if any QC status is Pending; "
                "otherwise the latest timestamp from metrics' status history"
            ),
        ),
    ]
