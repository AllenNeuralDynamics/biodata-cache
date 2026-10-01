"""Tests for record-consistency sources."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.record_consistency import sources
from biodata_cache.cache_table_helpers.record_consistency.framework import RECORD_FIELDS, SOURCES


class FakeDocDb:
    """In-memory stand-in for ``MetadataDbClient`` that honors filter, projection, sort, and limit."""

    def __init__(self, records):
        self.records = records
        self.calls = []

    def retrieve_docdb_records(self, filter_query=None, projection=None, sort=None, limit=0):
        self.calls.append({"filter_query": filter_query, "projection": projection, "sort": sort, "limit": limit})
        rows = sorted(self.records, key=lambda record: record["_id"])
        condition = (filter_query or {}).get("_id", {})
        if "$gt" in condition:
            rows = [row for row in rows if row["_id"] > condition["$gt"]]
        if "$in" in condition:
            rows = [row for row in rows if row["_id"] in condition["$in"]]
        if limit:
            rows = rows[:limit]
        return [{key: row[key] for key in projection if key in row} for row in rows]


@pytest.fixture
def v1_docdb():
    docdb = FakeDocDb([])
    with patch("aind_data_access_api.document_db.MetadataDbClient", return_value=docdb):
        yield docdb


def _v1(_id, name, last_modified="t1"):
    return {"_id": _id, "name": name, "location": f"s3://bucket/{name}", "last_modified": last_modified}


def _write_basics(rows):
    registry.BACKEND.write(
        registry.NAMES["basics"],
        pd.DataFrame(
            [[*row, None] if len(row) == 5 else row for row in rows],
            columns=["_id", "name", "location", "_last_modified", "subject_id", "code_ocean"],
        ),
    )


def test_docdb_v2_reads_records_from_asset_basics():
    _write_basics([["id-2", "b", "s3://bucket/b", "t2", "s1", ["co-1", "co-2"]], ["id-1", "a", None, "t1", "s1"]])

    records = SOURCES["docdb_v2"].load(pd.DataFrame())

    assert records == [
        {"record_id": "id-1", "name": "a", "location": None, "record_last_modified": "t1", "code_ocean_ids": []},
        {
            "record_id": "id-2",
            "name": "b",
            "location": "s3://bucket/b",
            "record_last_modified": "t2",
            "code_ocean_ids": ["co-1", "co-2"],
        },
    ]


def test_docdb_v2_skips_unusable_records_and_keeps_repeated_ids_once():
    _write_basics(
        [
            ["ok", "kept", None, None, "s1"],
            ["ok", "kept", None, None, "s1"],
            ["no-name", None, None, None, "s1"],
            ["empty-name", "", None, None, "s1"],
            [None, "no-id", None, None, "s1"],
        ]
    )

    assert [record["record_id"] for record in SOURCES["docdb_v2"].load(pd.DataFrame())] == ["ok"]


def test_docdb_v2_without_asset_basics_fails():
    with pytest.raises(ValueError, match="no records"):
        SOURCES["docdb_v2"].load(pd.DataFrame())


# --- docdb_v1 ---


def test_sweep_pages_after_the_last_id(monkeypatch):
    monkeypatch.setattr(sources, "DOCDB_PAGE_SIZE", 2)
    docdb = FakeDocDb([_v1(f"id-{index}", f"name-{index}") for index in range(4)])

    records = sources._sweep(docdb, {"_id": 1})

    assert [record["_id"] for record in records] == ["id-0", "id-1", "id-2", "id-3"]
    assert [call["filter_query"] for call in docdb.calls] == [{}, {"_id": {"$gt": "id-1"}}, {"_id": {"$gt": "id-3"}}]


def test_sweep_is_not_shifted_by_records_inserted_mid_sweep(monkeypatch):
    monkeypatch.setattr(sources, "DOCDB_PAGE_SIZE", 2)
    docdb = FakeDocDb([_v1("b", "b"), _v1("c", "c"), _v1("d", "d")])
    retrieve = docdb.retrieve_docdb_records

    def insert_after_each_page(**kwargs):
        page = retrieve(**kwargs)
        docdb.records.append(_v1("a", "a"))
        return page

    docdb.retrieve_docdb_records = insert_after_each_page

    assert [record["_id"] for record in sources._sweep(docdb, {"_id": 1})] == ["b", "c", "d"]


def test_docdb_v1_sweeps_every_field_without_previous_rows(v1_docdb):
    v1_docdb.records = [_v1("id-1", "one")]

    records = SOURCES["docdb_v1"].load(pd.DataFrame(columns=RECORD_FIELDS))

    assert records == [
        {"record_id": "id-1", "name": "one", "location": "s3://bucket/one", "record_last_modified": "t1"}
    ]
    assert len(v1_docdb.calls) == 1


def test_docdb_v1_refetches_only_new_and_changed_records(v1_docdb):
    previous = pd.DataFrame(
        [
            ["unchanged", "cached-name", "s3://bucket/cached", "t1"],
            ["changed", "old-name", "s3://bucket/old", "t1"],
            ["deleted", "deleted", "s3://bucket/deleted", "t1"],
        ],
        columns=RECORD_FIELDS,
    )
    v1_docdb.records = [
        _v1("unchanged", "renamed-without-new-timestamp", "t1"),
        _v1("changed", "new-name", "t2"),
        _v1("new", "new", "t1"),
        _v1("no-timestamp", "no-timestamp", None),
    ]

    records = SOURCES["docdb_v1"].load(previous)

    assert {record["record_id"]: record["name"] for record in records} == {
        "unchanged": "cached-name",
        "changed": "new-name",
        "new": "new",
        "no-timestamp": "no-timestamp",
    }
    assert sorted(v1_docdb.calls[-1]["filter_query"]["_id"]["$in"]) == ["changed", "new", "no-timestamp"]


def test_docdb_v1_with_no_records_fails(v1_docdb):
    with pytest.raises(ValueError, match="no records"):
        SOURCES["docdb_v1"].load(pd.DataFrame(columns=RECORD_FIELDS))


def test_aind_open_data_prefixes_lists_every_top_level_prefix():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"CommonPrefixes": [{"Prefix": "b-asset/"}, {"Prefix": "a-asset/"}]},
        {"CommonPrefixes": [{"Prefix": "c-asset/"}]},
        {},
    ]

    with patch("biodata_cache.cache_table_helpers.record_consistency.sources.boto3.client", return_value=client):
        records = SOURCES["aind_open_data_prefixes"].load(pd.DataFrame())

    client.get_paginator.return_value.paginate.assert_called_once_with(Bucket="aind-open-data", Delimiter="/")
    assert records[0] == {
        "record_id": "s3://aind-open-data/a-asset",
        "name": "a-asset",
        "location": "s3://aind-open-data/a-asset",
        "record_last_modified": None,
    }
    assert [record["name"] for record in records] == ["a-asset", "b-asset", "c-asset"]


# --- code_ocean_data_assets ---


def _asset(asset_id, name, bucket=None, prefix=None):
    source_bucket = None if bucket is None else SimpleNamespace(bucket=bucket, prefix=prefix)
    return SimpleNamespace(id=asset_id, name=name, source_bucket=source_bucket)


def test_code_ocean_data_assets_reads_every_non_archived_asset(monkeypatch):
    monkeypatch.setenv("CUSTOM_KEY", "token")
    client = MagicMock()
    client.data_assets.search_data_assets_iterator.return_value = iter(
        [
            _asset("co-2", "external", "aind-open-data", "external/"),
            _asset("co-1", "internal"),
            _asset("co-3", "bucket-root", "aind-scratch-data", None),
        ]
    )

    with patch("codeocean.CodeOcean", return_value=client) as code_ocean:
        records = SOURCES["code_ocean_data_assets"].load(pd.DataFrame())

    assert code_ocean.call_args.kwargs["token"] == "token"
    params = client.data_assets.search_data_assets_iterator.call_args.args[0]
    assert (params.archived, params.limit) == (False, sources.CODE_OCEAN_PAGE_SIZE)
    assert {record["record_id"]: record["location"] for record in records} == {
        "co-1": None,
        "co-2": "s3://aind-open-data/external",
        "co-3": "s3://aind-scratch-data",
    }
    assert {record["record_last_modified"] for record in records} == {None}


def test_code_ocean_data_assets_without_a_token_fails(monkeypatch):
    monkeypatch.delenv("CUSTOM_KEY", raising=False)

    with pytest.raises(ValueError, match="CUSTOM_KEY"):
        SOURCES["code_ocean_data_assets"].load(pd.DataFrame())
