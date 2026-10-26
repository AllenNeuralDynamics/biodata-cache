"""DocDB v2 locations that disagree with the record's Code Ocean data assets."""

from typing import Any

from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check


class CodeOceanLocationMismatchV2(Check):
    """Fail v2 records whose location disagrees with any linked, visible Code Ocean data asset."""

    description = (
        "Fails DocDB v2 records whose 'location' field does not match every visible Code Ocean data asset in "
        "'other_identifiers': the asset's S3 source, or its ID for assets stored in Code Ocean."
    )
    source = "docdb_v2"
    needs = ("code_ocean_data_assets",)
    compares_across_records = True

    def evaluate(self, records: list[dict[str, Any]], **needed: list[dict[str, Any]]) -> list[str | None]:
        """Skip records with no visible linked asset; fail any other record with a mismatching asset."""
        assets = {asset["record_id"]: asset["location"] for asset in needed["code_ocean_data_assets"]}
        statuses: list[str | None] = []
        for record in records:
            location = (record["location"] or "").rstrip("/")
            visible = [asset_id for asset_id in record["code_ocean_ids"] if asset_id in assets]
            if not visible:
                statuses.append(None)
                continue
            matches = all(
                location == assets[asset_id] if assets[asset_id] else location.rsplit("/", 1)[-1] == asset_id
                for asset_id in visible
            )
            statuses.append(PASS if matches else FAIL)
        return statuses
