"""DocDB v1 records with no counterpart name in DocDB v2."""

from typing import Any

from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check


class V1NameMissingInV2(Check):
    """Fail v1 records whose exact name matches no v2 record."""

    description = "Fails every DocDB v1 record whose non-empty `name` has zero exact matches in DocDB v2."
    source = "docdb_v1"
    needs = ("docdb_v2",)
    compares_across_records = True

    def evaluate(self, records: list[dict[str, Any]], **needed: list[dict[str, Any]]) -> list[str]:
        """Fail each v1 record whose name is absent from DocDB v2."""
        v2_names = {record["name"] for record in needed["docdb_v2"]}
        return [PASS if record["name"] in v2_names else FAIL for record in records]
