"""Sources, checks, and the snapshot builder for the record_consistency_checks table.

A ``Source`` loads one population of records. A ``Check`` evaluates the records of
one source, optionally against other sources, and returns ``pass`` or ``fail`` per
record. The builder loads each source once, runs every registered check, and writes
one snapshot of live state. Results of checks that do not compare across records
are reused for records whose ``record_last_modified`` and check code are unchanged.
"""

import hashlib
import inspect
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache import __version__
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

REPOSITORY_URL = "https://github.com/AllenNeuralDynamics/biodata-cache"
SOURCE_ROOT = Path(__file__).resolve().parents[3]
PASS = "pass"
FAIL = "fail"
RECORD_FIELDS = ["record_id", "name", "location", "record_last_modified"]
CHECK_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]*")

SOURCES: dict[str, "Source"] = {}
CHECKS: dict[str, "Check"] = {}


def _log(message: str) -> None:
    """Log a structured message for the record_consistency_checks table."""
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["record_consistency_checks"],
            message=message,
        ).to_json()
    )


def _without_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Replace pandas missing values with ``None``."""
    return df.astype(object).where(df.notna(), None)


class Source(ABC):
    """One population of records that checks evaluate or compare against."""

    name: ClassVar[str]
    record_kind: ClassVar[str]
    system: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register each concrete source under its unique ``name``."""
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        for attribute in ("name", "record_kind", "system"):
            if not isinstance(getattr(cls, attribute, None), str):
                raise TypeError(f"Source {cls.__name__} must define a string {attribute!r}")
        if cls.name in SOURCES:
            raise ValueError(f"Source {cls.name!r} is already registered")
        SOURCES[cls.name] = cls()

    @abstractmethod
    def fetch(self, previous: pd.DataFrame) -> pd.DataFrame:
        """Return the current records with columns ``RECORD_FIELDS``.

        Args:
            previous: This source's rows from the current snapshot, which a source may
                reuse instead of refetching records that have not changed.
        """

    def load(self, previous: pd.DataFrame) -> list[dict[str, Any]]:
        """Return valid records sorted by ``(name, record_id)``.

        Records without a string ``record_id`` and a non-empty string ``name`` are
        skipped, and a repeated ``record_id`` is kept once.

        Raises:
            ValueError: If the source has no valid records.
        """
        fetched = self.fetch(previous)
        frame = _without_missing(fetched.reindex(columns=RECORD_FIELDS).drop_duplicates(subset="record_id"))
        records = [
            record
            for record in frame.to_dict(orient="records")
            if isinstance(record["record_id"], str)
            and record["record_id"]
            and isinstance(record["name"], str)
            and record["name"]
        ]
        if not records:
            raise ValueError(f"Source {self.name!r} returned no records to check")
        _log(f"Source {self.name!r} loaded {len(records)} records ({len(fetched) - len(records)} skipped)")
        return sorted(records, key=lambda record: (record["name"], record["record_id"]))


class Check(ABC):
    """A record-consistency check, keyed by the name of the module that defines it."""

    description: ClassVar[str]
    source: ClassVar[str]
    needs: ClassVar[tuple[str, ...]] = ()
    compares_across_records: ClassVar[bool] = False

    key: ClassVar[str]
    hash: ClassVar[str]
    source_url: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register each concrete check, deriving its key, hash, and source link."""
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        path = Path(inspect.getsourcefile(cls)).resolve()
        key = path.stem
        if not CHECK_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"Check module name {key!r} is not a snake_case check key")
        if key in CHECKS:
            raise ValueError(f"Check {key!r} is already registered")
        if not isinstance(getattr(cls, "description", None), str) or not cls.description:
            raise TypeError(f"Check {key!r} must define a non-empty string 'description'")
        if not isinstance(getattr(cls, "source", None), str):
            raise TypeError(f"Check {key!r} must define a string 'source'")
        cls.key = key
        cls.hash = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        line = inspect.getsourcelines(cls)[1]
        cls.source_url = f"{REPOSITORY_URL}/blob/v{__version__}/src/{path.relative_to(SOURCE_ROOT).as_posix()}#L{line}"
        CHECKS[key] = cls()

    @abstractmethod
    def evaluate(self, records: list[dict[str, Any]], **needed: list[dict[str, Any]]) -> list[str]:
        """Return ``pass`` or ``fail`` for each record, in input order.

        Args:
            records: Valid records of ``source``.
            **needed: Valid records of each source in ``needs``, keyed by source name.
        """


def _validate_registrations() -> None:
    """Raise if a registered check names a source that is not registered."""
    for check in CHECKS.values():
        unknown = sorted({check.source, *check.needs} - set(SOURCES))
        if unknown:
            raise ValueError(f"Check {check.key!r} names unknown sources: {unknown}")


def _reusable_statuses(check: Check, previous: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Map ``(record_id, record_last_modified)`` to a previous status that is still valid."""
    if check.compares_across_records or previous.empty:
        return {}
    rows = previous[(previous["check_key"] == check.key) & (previous["check_hash"] == check.hash)]
    return {
        (row.record_id, row.record_last_modified): row.status
        for row in rows.itertuples(index=False)
        if row.record_last_modified is not None
    }


def _check_rows(check: Check, loaded: dict[str, list[dict[str, Any]]], previous: pd.DataFrame) -> pd.DataFrame:
    """Evaluate one check, reusing unchanged results where allowed, and return its rows."""
    records = loaded[check.source]
    reusable = _reusable_statuses(check, previous)
    pending = [record for record in records if (record["record_id"], record["record_last_modified"]) not in reusable]
    statuses = check.evaluate(pending, **{name: loaded[name] for name in check.needs})
    if len(statuses) != len(pending) or not set(statuses) <= {PASS, FAIL}:
        raise ValueError(f"Check {check.key!r} must return 'pass' or 'fail' for each record")
    evaluated = dict(zip((record["record_id"] for record in pending), statuses, strict=True))

    rows = pd.DataFrame(records, columns=RECORD_FIELDS)
    rows["status"] = [
        evaluated.get(record["record_id"]) or reusable[(record["record_id"], record["record_last_modified"])]
        for record in records
    ]
    rows["check_key"] = check.key
    rows["check_description"] = check.description
    rows["check_source_url"] = check.source_url
    rows["check_hash"] = check.hash
    rows["record_kind"] = SOURCES[check.source].record_kind
    _log(
        f"Check {check.key!r} evaluated {len(pending)} records, reused {len(records) - len(pending)}, "
        f"failed {(rows['status'] == FAIL).sum()}"
    )
    return rows


def build_snapshot(previous: pd.DataFrame, force_full_rerun: bool = False) -> pd.DataFrame:
    """Run every registered check and return the new snapshot.

    Args:
        previous: The current snapshot, used to skip unchanged records.
        force_full_rerun: If True, ignore ``previous`` and evaluate every record.

    Returns:
        One row per evaluated record and check, sorted by ``(check_key, name, record_id)``.
    """
    _validate_registrations()
    columns = [column.name for column in record_consistency_checks_columns()]
    if force_full_rerun or not set(columns) <= set(previous.columns):
        previous = pd.DataFrame(columns=columns)
    previous = _without_missing(previous)

    checks = [CHECKS[key] for key in sorted(CHECKS)]
    source_names = dict.fromkeys(name for check in checks for name in (check.source, *check.needs))
    loaded = {
        name: SOURCES[name].load(
            previous.loc[previous["record_kind"] == SOURCES[name].record_kind, RECORD_FIELDS].drop_duplicates(
                subset="record_id"
            )
        )
        for name in source_names
    }

    snapshot = pd.concat([_check_rows(check, loaded, previous) for check in checks], ignore_index=True)
    snapshot["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return snapshot.sort_values(["check_key", "name", "record_id"], ignore_index=True)[columns]


@registry.register_table(registry.NAMES["record_consistency_checks"])
def record_consistency_checks(force_update: bool = False, force_full_rerun: bool = False) -> pd.DataFrame:
    """Return the record-consistency snapshot, rebuilding it when forced or absent.

    Args:
        force_update: If True, rebuild the snapshot from live sources.
        force_full_rerun: If True, rebuild without reusing any previous result.

    Returns:
        One row per evaluated record and check.
    """
    table = registry.NAMES["record_consistency_checks"]
    previous = registry.BACKEND.read(table)
    if not previous.empty and not (force_update or force_full_rerun):
        return previous

    setup_logging()
    snapshot = build_snapshot(previous, force_full_rerun=force_full_rerun)
    registry.BACKEND.write(table, snapshot)
    return snapshot


def record_consistency_checks_columns() -> list[Column]:
    """Return record_consistency_checks cache table column definitions."""
    return [
        Column(name="check_key", description="Stable check identifier (the check module's name)"),
        Column(name="check_description", description="What the check fails"),
        Column(
            name="check_source_url",
            description="Link to the check in the biodata-cache release that produced this snapshot",
        ),
        Column(name="check_hash", description="Hash of the check module's source; gates reuse of previous results"),
        Column(name="status", description="Check result for this record: pass or fail"),
        Column(name="record_kind", description="Kind of record evaluated, for example docdb_v2"),
        Column(name="record_id", description="Record identifier in its source system, for example the DocDB _id"),
        Column(name="name", description="Record name"),
        Column(name="location", description="S3 location of the record, when the source provides it"),
        Column(
            name="record_last_modified",
            description="Last-modified timestamp of the record in its source system when it was checked",
        ),
        Column(name="checked_at", description="UTC time of the run that produced this snapshot"),
    ]
