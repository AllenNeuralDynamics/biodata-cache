"""Pure DocDB v2 record-consistency checks."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

CHECK_CLASS = "duplication"
CHECK_KEY = "docdb_duplicate_name_v2"
CHECK_DESCRIPTION = "Fails every DocDB v2 record whose non-empty `name` exactly matches another v2 record."
CHECK_IMPLEMENTATION_URL = (
    "https://github.com/AllenNeuralDynamics/biodata-cache/blob/5b10df0/"
    "src/biodata_cache/record_consistency.py#L39"
)
DOCDB_VERSION = "v2"
PROJECTION = {"_id": 1, "name": 1}


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
