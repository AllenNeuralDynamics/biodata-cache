"""Tests for record-consistency sources."""

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.record_consistency.framework import SOURCES


def _write_basics(rows):
    registry.BACKEND.write(
        registry.NAMES["basics"],
        pd.DataFrame(rows, columns=["_id", "name", "location", "_last_modified", "subject_id"]),
    )


def test_docdb_v2_reads_records_from_asset_basics():
    _write_basics([["id-2", "b", "s3://bucket/b", "t2", "s1"], ["id-1", "a", None, "t1", "s1"]])

    records = SOURCES["docdb_v2"].load(pd.DataFrame())

    assert records == [
        {"record_id": "id-1", "name": "a", "location": None, "record_last_modified": "t1"},
        {"record_id": "id-2", "name": "b", "location": "s3://bucket/b", "record_last_modified": "t2"},
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
