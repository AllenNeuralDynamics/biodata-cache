"""SmartSPIM fiber-tip CCF locations annotated through the QC portal."""

import json
import logging
import math

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.codeocean import CodeOceanBackend
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

# Must match the metric names zombie's QC page creates (web/src/qc/fiber-ccf.js).
METRIC_SUFFIX = " CCF Location"
AXES = ("AP", "ML", "DV")

COLUMNS = [
    "subject_id",
    "name",
    "fiber",
    "targeted_structure",
    "ap",
    "ml",
    "dv",
    "status",
    "evaluator",
    "status_timestamp",
    "ccf_link",
]


def _fetch_records() -> list[dict]:
    """Fetch stitched SPIM assets whose subject has a fiber probe implant."""
    if isinstance(registry.BACKEND, CodeOceanBackend):
        return [
            record
            for record in registry.BACKEND.load_records()
            if "_stitched_" in record["name"]
            and any(
                modality.get("abbreviation") == "SPIM" for modality in record["data_description"].get("modalities", [])
            )
            and any(
                (procedure.get("implanted_device") or {}).get("object_type") == "Fiber probe"
                for surgery in record["procedures"].get("subject_procedures", []) or []
                for procedure in surgery.get("procedures", []) or []
            )
        ]

    from aind_data_access_api.document_db import MetadataDbClient

    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
    return client.retrieve_docdb_records(
        filter_query={
            "data_description.modalities.abbreviation": "SPIM",
            "name": {"$regex": "_stitched_"},
            "procedures.subject_procedures.procedures.implanted_device.object_type": "Fiber probe",
        },
        projection={
            "_id": 1,
            "name": 1,
            "subject.subject_id": 1,
            "procedures.subject_procedures": 1,
            "quality_control.metrics": 1,
        },
        limit=0,
    )


def _fibers(record: dict) -> list[tuple[str, str | None]]:
    """Return (fiber name, targeted structure acronym) for each fiber probe implant."""
    fibers: dict[str, str | None] = {}
    for surgery in (record.get("procedures") or {}).get("subject_procedures") or []:
        for proc in surgery.get("procedures") or []:
            device = proc.get("implanted_device") or {}
            if proc.get("object_type") != "Probe implant" or device.get("object_type") != "Fiber probe":
                continue
            name = device.get("name")
            if not name or name in fibers:
                continue
            structure = ((proc.get("device_config") or {}).get("primary_targeted_structure") or {}).get("acronym")
            fibers[name] = structure
    return list(fibers.items())


def _decode_value(value):
    if isinstance(value, str):
        text = value[5:] if value.startswith("json:") else value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return value


def _index(value) -> int | None:
    """Coerce a user-entered coordinate to an integer index, or None if absent/invalid."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if isinstance(value, (int, float)) and math.isfinite(value) and float(value).is_integer():
        return int(value)
    return None


def _build_rows(records: list[dict]) -> list[dict]:
    """One row per (stitched asset, fiber); coordinates are null until annotated."""
    rows = []
    for record in records:
        metrics = {m.get("name"): m for m in ((record.get("quality_control") or {}).get("metrics") or [])}
        for fiber, structure in _fibers(record):
            metric = metrics.get(f"{fiber}{METRIC_SUFFIX}") or {}
            value = _decode_value(metric.get("value"))
            value = value if isinstance(value, dict) else {}
            history = metric.get("status_history") or []
            latest = history[-1] if history else {}
            rows.append(
                {
                    "subject_id": (record.get("subject") or {}).get("subject_id"),
                    "name": record.get("name"),
                    "fiber": fiber,
                    "targeted_structure": structure,
                    "ap": _index(value.get("AP")),
                    "ml": _index(value.get("ML")),
                    "dv": _index(value.get("DV")),
                    "status": latest.get("status"),
                    "evaluator": latest.get("evaluator"),
                    "status_timestamp": str(latest["timestamp"]) if latest.get("timestamp") else None,
                    "ccf_link": metric.get("reference"),
                }
            )
    return rows


def _to_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    for column in ("ap", "ml", "dv"):
        df[column] = df[column].astype("Int64")
    return df


@registry.register_table(registry.NAMES["smartspim_fiber_ccf"])
def platform_smartspim_fiber_ccf(force_update: bool = False) -> pd.DataFrame:
    """Build the fiber-tip CCF location table from SmartSPIM QC metrics.

    Args:
        force_update: If True, rebuild from the active metadata source.

    Returns:
        DataFrame with one row per (stitched SmartSPIM asset, fiber probe).
    """
    name = registry.NAMES["smartspim_fiber_ccf"]
    df = registry.BACKEND.read(name)

    local = isinstance(registry.BACKEND, CodeOceanBackend)
    missing = not registry.BACKEND.cache_exists(name) if local else df.empty
    if missing and not force_update and not local:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if missing or force_update:
        setup_logging()
        records = _fetch_records()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=name,
                message=f"Building fiber CCF rows from {len(records)} stitched SmartSPIM assets",
            ).to_json()
        )
        df = _to_frame(_build_rows(records))
        registry.BACKEND.write(name, df)

    return df


def platform_smartspim_fiber_ccf_columns() -> list[Column]:
    return [
        Column(name="subject_id", description="Subject ID"),
        Column(name="name", description="Stitched SmartSPIM asset name"),
        Column(name="fiber", description="Fiber probe name from the implant procedure (e.g. Fiber 0)"),
        Column(name="targeted_structure", description="Intended CCF structure acronym from the implant procedure"),
        Column(name="ap", description="Fiber tip AP index in the CCF-aligned volume (25um), null until annotated"),
        Column(name="ml", description="Fiber tip ML index in the CCF-aligned volume (25um), null until annotated"),
        Column(name="dv", description="Fiber tip DV index in the CCF-aligned volume (25um), null until annotated"),
        Column(name="status", description="Latest QC status of the fiber CCF Location metric, null if not created"),
        Column(name="evaluator", description="Evaluator of the latest QC status"),
        Column(name="status_timestamp", description="Timestamp of the latest QC status"),
        Column(name="ccf_link", description="Neuroglancer link to the CCF-aligned volume used for annotation"),
    ]
