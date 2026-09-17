"""Pure record-consistency checks."""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CHECK_CLASS = "duplication"
CHECK_KEY = "docdb_duplicate_name_v2"
CHECK_DESCRIPTION = 'Fails each record in DocDB v2 whose exact "name" key is identical to another v2 record.'
CHECK_IMPLEMENTATION_URL = (
    "https://github.com/AllenNeuralDynamics/biodata-cache/blob/5b10df0/src/biodata_cache/record_consistency.py#L39"
)
DOCDB_VERSION = "v2"
PROJECTION = {"_id": 1, "name": 1}
V1_NAME_MISSING_V2_CHECK_KEY = "docdb_v1_name_missing_in_v2"
V1_NAME_MISSING_V2_DOCDB_VERSION = "v1"
V1_NAME_MISSING_V2_PROJECTION = {"_id": 1, "name": 1}
OPEN_DATA_CODE_OCEAN_CHECK_KEY = "s3_open_data_prefix_code_ocean_external_asset"
OPEN_DATA_BUCKET = "aind-open-data"


@dataclass(frozen=True, slots=True)
class DuplicateNameCheckSummary:
    """Counts and invariants produced by the v2 duplicate-name check."""

    candidate_count: int
    processed_count: int
    skipped_count: int
    parse_failure_count: int
    failed_count: int
    duplicate_group_count: int

    @property
    def is_complete(self) -> bool:
        """Return whether every candidate was validly classified or intentionally skipped."""
        return self.parse_failure_count == 0

    def validate(self) -> None:
        """Raise if the summary's accounting invariant is violated."""
        accounted = self.processed_count + self.skipped_count + self.parse_failure_count
        if accounted != self.candidate_count:
            raise ValueError(
                f"Duplicate-name check accounting mismatch: candidate={self.candidate_count}, accounted={accounted}"
            )


@dataclass(frozen=True, slots=True)
class V1NameMissingV2CheckSummary:
    """Counts and invariants produced by the v1-name coverage check."""

    candidate_count: int
    processed_count: int
    skipped_count: int
    parse_failure_count: int
    failed_count: int

    @property
    def is_complete(self) -> bool:
        """Return whether every candidate was validly classified or intentionally skipped."""
        return self.parse_failure_count == 0

    def validate(self) -> None:
        """Raise if the summary's accounting invariant is violated."""
        accounted = self.processed_count + self.skipped_count + self.parse_failure_count
        if accounted != self.candidate_count:
            raise ValueError(
                f"V1-name coverage check accounting mismatch: candidate={self.candidate_count}, accounted={accounted}"
            )


@dataclass(frozen=True, slots=True)
class OpenDataCodeOceanCheckSummary:
    """Counts produced by the open-data Code Ocean coverage check."""

    candidate_count: int
    processed_count: int
    passed_count: int
    failed_count: int
    unknown_count: int

    @property
    def is_complete(self) -> bool:
        """Return whether every S3 prefix received a result."""
        return self.processed_count == self.candidate_count

    def validate(self) -> None:
        """Raise if the summary's accounting invariant is violated."""
        accounted = self.passed_count + self.failed_count + self.unknown_count
        if accounted != self.processed_count or self.processed_count != self.candidate_count:
            raise ValueError(
                "Open-data Code Ocean check accounting mismatch: "
                f"candidate={self.candidate_count}, processed={self.processed_count}, accounted={accounted}"
            )


def evaluate_duplicate_names_v2(
    records: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], DuplicateNameCheckSummary]:
    """Evaluate exact duplicate names in one DocDB v2 population.

    Records with the same exact, non-empty ``name`` are one duplicate group. Every
    member of a group with at least two records receives ``status == "fail"`` and
    the complete set of peer IDs. Valid singleton records receive ``status ==
    "pass"``. Missing or empty names are skipped; malformed records are counted as
    parse failures and never become duplicate findings.

    The function is intentionally v2-specific. A future v1 check must call a
    separately named function or explicitly provide a separate versioned input;
    this function must never combine the two populations.

    Args:
        records: Iterable of projected DocDB records containing string ``_id``
            and ``name`` fields.

    Returns:
        A deterministic list of result rows and the input/result summary.

    Raises:
        ValueError: If the input contains the same DocDB ID more than once.
            Duplicate IDs make the source sweep invalid and must not be silently
            interpreted as duplicate names.
    """
    candidates = list(records)
    valid_records: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    skipped_count = 0
    parse_failure_count = 0

    for index, record in enumerate(candidates):
        if not isinstance(record, Mapping):
            parse_failure_count += 1
            continue

        docdb_id = record.get("_id")
        if not isinstance(docdb_id, str) or not docdb_id:
            parse_failure_count += 1
            continue
        if docdb_id in seen_ids:
            raise ValueError(f"Duplicate DocDB ID in v2 input at record index {index}: {docdb_id!r}")
        seen_ids.add(docdb_id)

        name = record.get("name")
        if name is None or name == "":
            skipped_count += 1
            continue
        if not isinstance(name, str):
            parse_failure_count += 1
            continue

        valid_records.append((docdb_id, name))

    records_by_name: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for record in valid_records:
        records_by_name[record[1]].append(record)

    result_rows: list[dict[str, Any]] = []
    duplicate_group_count = 0
    for name in sorted(records_by_name):
        group = sorted(records_by_name[name], key=lambda record: record[0])
        group_count = len(group)
        if group_count > 1:
            duplicate_group_count += 1

        for docdb_id, _ in group:
            peers = [peer for peer in group if peer[0] != docdb_id]
            failed = bool(peers)
            result_rows.append(
                {
                    "check_key": CHECK_KEY,
                    "check_class": CHECK_CLASS,
                    "docdb_version": DOCDB_VERSION,
                    "docdb_id": docdb_id,
                    "name": name,
                    "status": "fail" if failed else "pass",
                    "duplicate_group_count": group_count,
                    "peer_docdb_ids": [peer[0] for peer in peers],
                    "peer_names": [peer[1] for peer in peers],
                    "reason": "multiple v2 DocDB records share this exact name" if failed else None,
                    "error_type": None,
                }
            )

    summary = DuplicateNameCheckSummary(
        candidate_count=len(candidates),
        processed_count=len(valid_records),
        skipped_count=skipped_count,
        parse_failure_count=parse_failure_count,
        failed_count=sum(row["status"] == "fail" for row in result_rows),
        duplicate_group_count=duplicate_group_count,
    )
    summary.validate()
    return result_rows, summary


def evaluate_v1_names_missing_v2(
    v1_records: Iterable[Mapping[str, Any]],
    v2_names: Collection[str],
) -> tuple[list[dict[str, Any]], V1NameMissingV2CheckSummary]:
    """Evaluate whether each DocDB v1 name has at least one exact v2 match.

    A valid v1 record passes when one or more v2 records have the same exact,
    non-empty ``name`` and fails when no v2 name matches. Missing or empty v1
    names are skipped. Malformed records are counted as parse failures.

    Args:
        v1_records: Complete projected DocDB v1 population containing ``_id``
            and ``name`` fields.
        v2_names: Validated set-like collection of exact DocDB v2 names.

    Returns:
        Deterministically ordered result rows and source-accounting summary.

    Raises:
        ValueError: If a reference v2 name is invalid or a v1 DocDB ID appears
            more than once.
    """
    invalid_v2_names = [name for name in v2_names if not isinstance(name, str) or not name]
    if invalid_v2_names:
        raise ValueError("v2_names must contain only non-empty strings")
    reference_names = set(v2_names)

    candidates = list(v1_records)
    valid_records: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    skipped_count = 0
    parse_failure_count = 0

    for index, record in enumerate(candidates):
        if not isinstance(record, Mapping):
            parse_failure_count += 1
            continue

        docdb_id = record.get("_id")
        if not isinstance(docdb_id, str) or not docdb_id:
            parse_failure_count += 1
            continue
        if docdb_id in seen_ids:
            raise ValueError(f"Duplicate DocDB ID in v1 input at record index {index}: {docdb_id!r}")
        seen_ids.add(docdb_id)

        name = record.get("name")
        if name is None or name == "":
            skipped_count += 1
            continue
        if not isinstance(name, str):
            parse_failure_count += 1
            continue
        valid_records.append((docdb_id, name))

    result_rows = [
        {
            "check_key": V1_NAME_MISSING_V2_CHECK_KEY,
            "docdb_version": V1_NAME_MISSING_V2_DOCDB_VERSION,
            "docdb_id": docdb_id,
            "name": name,
            "status": "pass" if name in reference_names else "fail",
        }
        for docdb_id, name in sorted(valid_records, key=lambda record: (record[1], record[0]))
    ]
    summary = V1NameMissingV2CheckSummary(
        candidate_count=len(candidates),
        processed_count=len(valid_records),
        skipped_count=skipped_count,
        parse_failure_count=parse_failure_count,
        failed_count=sum(row["status"] == "fail" for row in result_rows),
    )
    summary.validate()
    return result_rows, summary


def evaluate_open_data_code_ocean_assets(
    prefixes: Iterable[str],
    code_ocean_assets: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], OpenDataCodeOceanCheckSummary]:
    """Match every top-level open-data S3 prefix to a Code Ocean external asset.

    A prefix passes when at least one visible Code Ocean asset has the exact folder
    name and externally references the exact S3 bucket and prefix. A visible
    exact-name asset with no correct target fails. No visible exact-name asset is
    unknown because the API result is limited by the caller's permissions.

    Args:
        prefixes: Complete top-level ``CommonPrefixes`` values from
            ``aind-open-data``.
        code_ocean_assets: Visible external assets projected to ``name``,
            ``bucket``, ``prefix``, and ``external``.

    Returns:
        Deterministically ordered result rows and source-accounting summary.

    Raises:
        ValueError: If an S3 prefix is malformed or repeated, or a Code Ocean
            projection is malformed.
    """
    candidates = list(prefixes)
    if len(set(candidates)) != len(candidates):
        raise ValueError("S3 prefix input contains duplicates")

    assets_by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for index, asset in enumerate(code_ocean_assets):
        if not isinstance(asset, Mapping):
            raise ValueError(f"Malformed Code Ocean asset at index {index}")
        name = asset.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"Malformed Code Ocean asset name at index {index}")
        assets_by_name[name].append(asset)

    rows: list[dict[str, Any]] = []
    for prefix in sorted(candidates):
        if not isinstance(prefix, str) or not prefix.endswith("/"):
            raise ValueError(f"Malformed top-level S3 prefix: {prefix!r}")

        name = prefix[:-1]
        location = f"s3://{OPEN_DATA_BUCKET}/{prefix}"
        if not name:
            status = "unknown"
        else:
            exact_name_assets = assets_by_name.get(name, [])
            correct_assets = [
                asset
                for asset in exact_name_assets
                if asset.get("bucket") == OPEN_DATA_BUCKET
                and _normalize_s3_prefix(asset.get("prefix")) == name
                and asset.get("external") is True
            ]
            if correct_assets:
                status = "pass"
            elif exact_name_assets:
                status = "fail"
            else:
                status = "unknown"

        rows.append(
            {
                "check_key": OPEN_DATA_CODE_OCEAN_CHECK_KEY,
                "docdb_version": None,
                "docdb_id": None,
                "name": name or prefix,
                "location": location,
                "status": status,
            }
        )

    summary = OpenDataCodeOceanCheckSummary(
        candidate_count=len(candidates),
        processed_count=len(rows),
        passed_count=sum(row["status"] == "pass" for row in rows),
        failed_count=sum(row["status"] == "fail" for row in rows),
        unknown_count=sum(row["status"] == "unknown" for row in rows),
    )
    summary.validate()
    return rows, summary


def _normalize_s3_prefix(value: Any) -> str | None:
    """Normalize a Code Ocean S3 prefix for exact folder comparison."""
    if not isinstance(value, str):
        return None
    return value.strip("/")
