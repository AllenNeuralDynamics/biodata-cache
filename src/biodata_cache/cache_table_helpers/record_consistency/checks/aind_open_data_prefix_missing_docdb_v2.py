"""Public aind-open-data prefixes without a DocDB v2 record."""

from typing import Any

from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check


class OpenDataPrefixMissingDocDbV2(Check):
    """Fail top-level aind-open-data prefixes that no DocDB v2 record points to."""

    description = "Fails every top-level aind-open-data prefix that no DocDB v2 record's `location` points to."
    source = "aind_open_data_prefixes"
    needs = ("docdb_v2",)
    compares_across_records = True

    def evaluate(self, records: list[dict[str, Any]], **needed: list[dict[str, Any]]) -> list[str]:
        """Fail each prefix whose S3 URI matches no v2 record location."""
        locations = {record["location"].rstrip("/") for record in needed["docdb_v2"] if record["location"]}
        return [PASS if record["location"] in locations else FAIL for record in records]
