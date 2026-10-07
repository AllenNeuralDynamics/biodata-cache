"""Record sources for record-consistency checks."""

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.record_consistency.framework import RECORD_FIELDS, Source

ASSET_BASICS_COLUMNS = {
    "_id": "record_id",
    "name": "name",
    "location": "location",
    "_last_modified": "record_last_modified",
}


class DocDbV2(Source):
    """DocDB v2 records, read from the cached ``asset_basics`` table."""

    name = "docdb_v2"
    record_kind = "docdb_v2"
    system = "docdb"

    def fetch(self, previous: pd.DataFrame) -> pd.DataFrame:
        """Return every v2 record in ``asset_basics``; ``previous`` is not needed."""
        basics = registry.BACKEND.read_filtered(
            registry.NAMES["basics"], columns=list(ASSET_BASICS_COLUMNS), limit=None
        )
        return basics.rename(columns=ASSET_BASICS_COLUMNS)[RECORD_FIELDS]
