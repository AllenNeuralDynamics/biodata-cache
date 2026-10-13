"""Record sources for record-consistency checks."""

import os
from typing import Any

import boto3
import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.record_consistency.framework import RECORD_FIELDS, Source

ASSET_BASICS_COLUMNS = {
    "_id": "record_id",
    "name": "name",
    "location": "location",
    "_last_modified": "record_last_modified",
    "code_ocean": "code_ocean_ids",
}


def _id_list(ids: Any) -> list[str]:
    """Return a record's Code Ocean data asset IDs as a list of strings."""
    if ids is None or isinstance(ids, float):
        return []
    return [str(asset_id) for asset_id in ids]


class DocDbV2(Source):
    """DocDB v2 records, read from the cached ``asset_basics`` table."""

    name = "docdb_v2"
    record_kind = "docdb_v2"
    system = "docdb"
    extra_fields = ("code_ocean_ids",)

    def fetch(self, previous: pd.DataFrame) -> pd.DataFrame:
        """Return every v2 record in ``asset_basics``; ``previous`` is not needed."""
        basics = registry.BACKEND.read_filtered(
            registry.NAMES["basics"], columns=list(ASSET_BASICS_COLUMNS), limit=None
        ).rename(columns=ASSET_BASICS_COLUMNS)
        basics["code_ocean_ids"] = basics["code_ocean_ids"].map(_id_list)
        return basics[[*RECORD_FIELDS, *self.extra_fields]]


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


OPEN_DATA_BUCKET = "aind-open-data"


class AindOpenDataPrefixes(Source):
    """Top-level prefixes of the public ``aind-open-data`` bucket."""

    name = "aind_open_data_prefixes"
    record_kind = "s3_prefix"
    system = "s3"

    def fetch(self, previous: pd.DataFrame) -> pd.DataFrame:
        """Return one record per top-level prefix; S3 prefixes have no last-modified time."""
        paginator = boto3.client("s3").get_paginator("list_objects_v2")
        prefixes = [
            common_prefix["Prefix"].rstrip("/")
            for page in paginator.paginate(Bucket=OPEN_DATA_BUCKET, Delimiter="/")
            for common_prefix in page.get("CommonPrefixes", [])
        ]
        uris = [f"s3://{OPEN_DATA_BUCKET}/{prefix}" for prefix in prefixes]
        return pd.DataFrame(
            {"record_id": uris, "name": prefixes, "location": uris, "record_last_modified": None},
            columns=RECORD_FIELDS,
        )


CODE_OCEAN_DOMAIN = "https://codeocean.allenneuraldynamics.org"
CODE_OCEAN_TOKEN_VARIABLE = "CUSTOM_KEY"
CODE_OCEAN_PAGE_SIZE = 1000
CODE_OCEAN_RETRIES = 3


def _source_uri(asset) -> str | None:
    """Return the S3 URI a data asset was created from, or None for assets stored in Code Ocean."""
    bucket = asset.source_bucket
    if bucket is None or not bucket.bucket:
        return None
    return f"s3://{bucket.bucket}/{bucket.prefix or ''}".rstrip("/")


class CodeOceanDataAssets(Source):
    """Non-archived Code Ocean data assets visible to the token in ``CUSTOM_KEY``."""

    name = "code_ocean_data_assets"
    record_kind = "code_ocean_data_asset"
    system = "code_ocean"

    def fetch(self, previous: pd.DataFrame) -> pd.DataFrame:
        """Return one record per data asset; the search API has no last-modified time."""
        from codeocean import CodeOcean
        from codeocean.data_asset import DataAssetSearchParams

        token = os.environ.get(CODE_OCEAN_TOKEN_VARIABLE)
        if not token:
            raise ValueError(f"Set {CODE_OCEAN_TOKEN_VARIABLE} to a Code Ocean API token to read data assets")
        client = CodeOcean(domain=CODE_OCEAN_DOMAIN, token=token, retries=CODE_OCEAN_RETRIES)
        assets = client.data_assets.search_data_assets_iterator(
            DataAssetSearchParams(archived=False, limit=CODE_OCEAN_PAGE_SIZE)
        )
        return pd.DataFrame(
            [[asset.id, asset.name, _source_uri(asset), None] for asset in assets],
            columns=RECORD_FIELDS,
        )
