"""Record-consistency checks cache table: one row per evaluated DocDB record and check.

Each check marks every record it evaluates ``pass`` or ``fail``. The check's
description and a link to its source are carried on every row, so consumers read
this one table and nothing else.
"""

import inspect
import logging
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache import __version__
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

REPOSITORY_URL = "https://github.com/AllenNeuralDynamics/biodata-cache"
RECORD_COLUMNS = ["_id", "name", "location", "_last_modified"]
PASS = "pass"
FAIL = "fail"

DUPLICATE_NAME_V2 = "docdb_duplicate_name_v2"
DUPLICATE_NAME_V2_DESCRIPTION = "Fails every DocDB v2 record whose non-empty `name` exactly matches another v2 record."


def duplicate_names(records: list[dict[str, Any]]) -> list[str]:
    """Fail every record whose exact name is shared with another record.

    Args:
        records: Records from one DocDB version, each with a non-empty ``name``.

    Returns:
        One status per record, in input order.
    """
    counts = Counter(record["name"] for record in records)
    return [FAIL if counts[record["name"]] > 1 else PASS for record in records]


def _valid_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Return records with a string ``_id`` and a non-empty string ``name``.

    A record repeated by ``_id`` is kept once. Records are sorted by ``(name, _id)``.
    """
    frame = df.reindex(columns=RECORD_COLUMNS).drop_duplicates(subset="_id")
    frame = frame.astype(object).where(frame.notna(), None)
    records = [
        record
        for record in frame.to_dict(orient="records")
        if isinstance(record["_id"], str) and record["_id"] and isinstance(record["name"], str) and record["name"]
    ]
    return sorted(records, key=lambda record: (record["name"], record["_id"]))


def _source_url(check: Callable) -> str:
    """Return a link to ``check`` in the tagged release of biodata-cache that ran it."""
    source_root = Path(__file__).resolve().parents[2]
    path = Path(inspect.getsourcefile(check)).resolve().relative_to(source_root)
    line = inspect.getsourcelines(check)[1]
    return f"{REPOSITORY_URL}/blob/v{__version__}/src/{path.as_posix()}#L{line}"


def _check_rows(
    check_key: str,
    description: str,
    check: Callable[..., list[str]],
    docdb_version: str,
    records: list[dict[str, Any]],
    **check_kwargs: Any,
) -> pd.DataFrame:
    """Run one check over ``records`` and return its rows."""
    rows = pd.DataFrame(records, columns=RECORD_COLUMNS)
    rows.insert(0, "check_key", check_key)
    rows.insert(1, "status", check(records, **check_kwargs))
    rows.insert(2, "docdb_version", docdb_version)
    rows["check_description"] = description
    rows["check_source_url"] = _source_url(check)
    return rows


@registry.register_table(registry.NAMES["record_consistency_checks"])
def record_consistency_checks(force_update: bool = False) -> pd.DataFrame:
    """Run every record-consistency check against the cached DocDB records.

    Args:
        force_update: If True, re-run the checks instead of returning the cached table.

    Returns:
        One row per evaluated record and check.

    Raises:
        ValueError: If ``asset_basics`` has no records to check.
    """
    table = registry.NAMES["record_consistency_checks"]
    if not force_update:
        df = registry.BACKEND.read(table)
        if not df.empty:
            return df

    setup_logging()
    basics = registry.BACKEND.read_filtered(registry.NAMES["basics"], columns=RECORD_COLUMNS, limit=None)
    v2_records = _valid_records(basics)
    if not v2_records:
        raise ValueError("asset_basics has no records to check; run the asset_basics job first")
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=table,
            message=f"Checking {len(v2_records)} v2 records ({len(basics) - len(v2_records)} skipped)",
        ).to_json()
    )

    df = _check_rows(DUPLICATE_NAME_V2, DUPLICATE_NAME_V2_DESCRIPTION, duplicate_names, "v2", v2_records)
    df["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    df = df[[column.name for column in record_consistency_checks_columns()]]
    registry.BACKEND.write(table, df)
    return df


def record_consistency_checks_columns() -> list[Column]:
    """Return record_consistency_checks cache table column definitions."""
    return [
        Column(name="check_key", description="Stable identifier of the check"),
        Column(name="status", description="Check result for this record: pass or fail"),
        Column(name="docdb_version", description="DocDB version of the evaluated record (v1 or v2)"),
        Column(name="_id", description="DocDB record ID"),
        Column(name="name", description="DocDB record name"),
        Column(name="location", description="S3 location of the DocDB record"),
        Column(name="_last_modified", description="DocDB last modified timestamp of the record when it was checked"),
        Column(name="checked_at", description="UTC time of the run that produced this row"),
        Column(name="check_description", description="What the check fails"),
        Column(name="check_source_url", description="Source of the check in the biodata-cache release that ran it"),
    ]
