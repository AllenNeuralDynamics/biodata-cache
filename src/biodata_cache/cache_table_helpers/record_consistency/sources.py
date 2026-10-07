"""Record sources for record-consistency checks."""

from typing import Any

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


V1_FIELDS = {"_id": "record_id", "name": "name", "location": "location", "last_modified": "record_last_modified"}
V1_LAST_MODIFIED_PROJECTION = {"_id": 1, "last_modified": 1}
DOCDB_PAGE_SIZE = 1000
DOCDB_ID_BATCH_SIZE = 100


def _sweep(client, projection: dict[str, int]) -> list[dict[str, Any]]:
    """Return every record in the client's collection, paging in ``_id`` order.

    Each page starts after the last ``_id`` already read, so records written during
    the sweep cannot shift later pages the way ``skip`` pagination does.
    """
    records: list[dict[str, Any]] = []
    while True:
        page = client.retrieve_docdb_records(
            filter_query={"_id": {"$gt": records[-1]["_id"]}} if records else {},
            projection=projection,
            sort={"_id": 1},
            limit=DOCDB_PAGE_SIZE,
        )
        records.extend(page)
        if len(page) < DOCDB_PAGE_SIZE:
            return records


def _fetch_by_id(client, ids: list[str], projection: dict[str, int]) -> list[dict[str, Any]]:
    """Return the records with the given IDs, fetched in batches."""
    records: list[dict[str, Any]] = []
    for start in range(0, len(ids), DOCDB_ID_BATCH_SIZE):
        records.extend(
            client.retrieve_docdb_records(
                filter_query={"_id": {"$in": ids[start : start + DOCDB_ID_BATCH_SIZE]}},
                projection=projection,
                limit=0,
            )
        )
    return records


class DocDbV1(Source):
    """DocDB v1 records, refetching only records modified since the previous snapshot."""

    name = "docdb_v1"
    record_kind = "docdb_v1"
    system = "docdb"

    def fetch(self, previous: pd.DataFrame) -> pd.DataFrame:
        """Return every v1 record, reusing ``previous`` rows whose ``last_modified`` is unchanged."""
        from aind_data_access_api.document_db import MetadataDbClient

        client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v1")
        projection = dict.fromkeys(V1_FIELDS, 1)
        if previous.empty:
            return pd.DataFrame(_sweep(client, projection), columns=list(V1_FIELDS)).rename(columns=V1_FIELDS)

        known = dict(zip(previous["record_id"], previous["record_last_modified"], strict=True))
        current = _sweep(client, V1_LAST_MODIFIED_PROJECTION)
        unchanged = {
            record["_id"]
            for record in current
            if record.get("last_modified") is not None and known.get(record["_id"]) == record["last_modified"]
        }
        fetched = _fetch_by_id(
            client, [record["_id"] for record in current if record["_id"] not in unchanged], projection
        )
        reused = previous[previous["record_id"].isin(unchanged)]
        fetched_rows = pd.DataFrame(fetched, columns=list(V1_FIELDS)).rename(columns=V1_FIELDS)
        return pd.DataFrame(
            [*reused.to_dict(orient="records"), *fetched_rows.to_dict(orient="records")], columns=RECORD_FIELDS
        )
