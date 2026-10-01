"""Duplicate record names within DocDB v2."""

from collections import Counter
from typing import Any

from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check


class DuplicateNameV2(Check):
    """Fail v2 records that share an exact name with another v2 record."""

    description = (
        "Fails DocDB v2 records whose 'name' field exactly matches the 'name' field of another DocDB v2 record."
    )
    source = "docdb_v2"
    compares_across_records = True

    def evaluate(self, records: list[dict[str, Any]], **needed: list[dict[str, Any]]) -> list[str]:
        """Fail each record whose name appears more than once."""
        counts = Counter(record["name"] for record in records)
        return [FAIL if counts[record["name"]] > 1 else PASS for record in records]
