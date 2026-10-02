"""Cache the standard SPIM QC metrics applied to derived SmartSPIM/ExaSPIM assets."""

import logging
import re

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

BASE_METRIC_NAMES = {
    "Image and tissue quality",
    "Tissue perfusion",
    "Flatfield correction",
    "Image destriping",
    "Image stitching",
}
BRIGHTNESS_SUFFIX = " brightness"

COLUMNS = [
    "subject_id",
    "name",
    "metric_name",
    "channel",
    "stage",
    "value",
    "status",
    "evaluator",
    "status_timestamp",
]


def _fetch_records() -> list[dict]:
    """Fetch derived SPIM instrument records and their acquisition/QC metadata."""
    from aind_data_access_api.document_db import MetadataDbClient

    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
    return client.retrieve_docdb_records(
        filter_query={
            "data_description.data_level": "derived",
            "instrument.instrument_id": {"$regex": "(smart|exa)", "$options": "i"},
            "quality_control.metrics": {"$exists": True},
        },
        projection={
            "name": 1,
            "subject.subject_id": 1,
            "data_description.data_level": 1,
            "instrument.instrument_id": 1,
            "acquisition.channels": 1,
            "quality_control.metrics": 1,
        },
        limit=0,
    )


def _channel_names(record: dict) -> list[str]:
    """Return channel names from acquisition metadata, preserving metadata order."""
    channels = ((record.get("acquisition") or {}).get("channels") or [])
    names = []
    for channel in channels:
        name = channel if isinstance(channel, str) else (channel or {}).get("channel_name")
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name)
    return names


def _is_qualifying_record(record: dict) -> bool:
    instrument_id = ((record.get("instrument") or {}).get("instrument_id") or "")
    return (
        (record.get("data_description") or {}).get("data_level") == "derived"
        and re.search(r"(smart|exa)", instrument_id, flags=re.IGNORECASE) is not None
    )


def _metric_value(value):
    """Return the scalar value stored inside structured QC metric values."""
    return value.get("value") if isinstance(value, dict) else value


def _standard_metric_names(channels: list[str]) -> set[str]:
    return BASE_METRIC_NAMES | {f"{channel}{BRIGHTNESS_SUFFIX}" for channel in channels}


def _build_rows(records: list[dict]) -> list[dict]:
    """Flatten each matching standard metric to one row per derived asset."""
    rows = []
    for record in records:
        if not _is_qualifying_record(record):
            continue

        channels = _channel_names(record)
        channel_by_metric = {f"{channel}{BRIGHTNESS_SUFFIX}": channel for channel in channels}
        metric_names = _standard_metric_names(channels)
        quality_control = record.get("quality_control") or {}
        for metric in quality_control.get("metrics") or []:
            metric_name = metric.get("name")
            if metric_name not in metric_names:
                continue

            history = metric.get("status_history") or []
            latest = history[-1] if history else {}
            rows.append(
                {
                    "subject_id": (record.get("subject") or {}).get("subject_id")
                    or (record.get("data_description") or {}).get("subject_id"),
                    "name": record.get("name"),
                    "metric_name": metric_name,
                    "channel": channel_by_metric.get(metric_name),
                    "stage": metric.get("stage"),
                    "value": _metric_value(metric.get("value")),
                    "status": latest.get("status"),
                    "evaluator": latest.get("evaluator"),
                    "status_timestamp": str(latest["timestamp"]) if latest.get("timestamp") else None,
                }
            )
    return rows


@registry.register_table(registry.NAMES["smartspim_qc_metrics"])
def platform_smartspim_qc_metrics(force_update: bool = False) -> pd.DataFrame:
    """Build the standard SPIM QC metrics table from derived asset metadata.

    Args:
        force_update: If True, rebuild from DocDB.

    Returns:
        DataFrame with one row per standard SPIM QC metric found on a derived
        SmartSPIM or ExaSPIM asset.
    """
    name = registry.NAMES["smartspim_qc_metrics"]
    df = registry.BACKEND.read(name)

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if df.empty or force_update:
        setup_logging()
        records = _fetch_records()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=name,
                message=f"Caching standard SPIM QC metrics from {len(records)} derived SmartSPIM/ExaSPIM assets",
            ).to_json()
        )
        df = pd.DataFrame(_build_rows(records), columns=COLUMNS)
        registry.BACKEND.write(name, df)

    return df


def platform_smartspim_qc_metrics_columns() -> list[Column]:
    return [
        Column(name="subject_id", description="Subject ID"),
        Column(name="name", description="Derived SmartSPIM or ExaSPIM asset name"),
        Column(name="metric_name", description="Standard SPIM QC metric name"),
        Column(name="channel", description="Acquisition channel for a brightness metric"),
        Column(name="stage", description="QC stage"),
        Column(name="value", description="QC metric value"),
        Column(name="status", description="Latest QC status, if evaluated"),
        Column(name="evaluator", description="Evaluator of the latest QC status"),
        Column(name="status_timestamp", description="Timestamp of the latest QC status"),
    ]
