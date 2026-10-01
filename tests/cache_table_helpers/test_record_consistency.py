"""Unit tests for the record_consistency_checks cache table."""

import inspect
import re

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers.record_consistency import (
    DUPLICATE_NAME_V2,
    _source_url,
    _valid_records,
    duplicate_names,
    record_consistency_checks,
    record_consistency_checks_columns,
)


@pytest.fixture(autouse=True)
def reset_backend():
    registry.BACKEND = MemoryBackend()


def _basics(rows):
    return pd.DataFrame(rows, columns=["_id", "name", "location", "_last_modified", "subject_id"])


# --- duplicate_names ---


def test_duplicate_names_fails_every_record_sharing_a_name():
    records = [{"name": "a"}, {"name": "b"}, {"name": "a"}, {"name": "a"}]
    assert duplicate_names(records) == ["fail", "pass", "fail", "fail"]


def test_duplicate_names_matches_names_exactly():
    records = [{"name": "Asset"}, {"name": "asset"}, {"name": "asset "}]
    assert duplicate_names(records) == ["pass", "pass", "pass"]


# --- _valid_records ---


def test_valid_records_skips_records_without_string_id_and_name():
    df = pd.DataFrame(
        {
            "_id": ["ok", "no-name", "empty-name", "number-name", None, 7],
            "name": ["kept", None, "", 3, "no-id", "int-id"],
        }
    )
    assert [record["_id"] for record in _valid_records(df)] == ["ok"]


def test_valid_records_treats_pandas_missing_values_as_missing():
    df = pd.DataFrame({"_id": ["a", "b"], "name": pd.array(["kept", pd.NA], dtype="string")})
    records = _valid_records(df)
    assert [record["_id"] for record in records] == ["a"]
    assert records[0]["location"] is None
    assert records[0]["_last_modified"] is None


def test_valid_records_keeps_a_repeated_id_once_and_sorts_by_name_then_id():
    df = pd.DataFrame({"_id": ["c", "b", "a", "b"], "name": ["y", "x", "y", "x"]})
    assert [(record["name"], record["_id"]) for record in _valid_records(df)] == [
        ("x", "b"),
        ("y", "a"),
        ("y", "c"),
    ]


# --- _source_url ---


def test_source_url_links_the_check_in_its_release():
    url = _source_url(duplicate_names)
    line = inspect.getsourcelines(duplicate_names)[1]
    assert re.fullmatch(
        rf"https://github\.com/AllenNeuralDynamics/biodata-cache/blob/v\d+\.\d+\.\d+/"
        rf"src/biodata_cache/cache_table_helpers/record_consistency\.py#L{line}",
        url,
    )


# --- record_consistency_checks ---


def test_record_consistency_checks_flags_duplicate_v2_names():
    registry.BACKEND.write(
        registry.NAMES["basics"],
        _basics(
            [
                ["id-2", "dup", "s3://bucket/dup-2", "2026-01-02", "s1"],
                ["id-1", "dup", "s3://bucket/dup-1", "2026-01-01", "s1"],
                ["id-3", "unique", "s3://bucket/unique", "2026-01-03", "s2"],
                ["id-4", None, "s3://bucket/unnamed", "2026-01-04", "s3"],
            ]
        ),
    )

    df = record_consistency_checks(force_update=True)

    assert list(df.columns) == [column.name for column in record_consistency_checks_columns()]
    assert df[["_id", "name", "status"]].values.tolist() == [
        ["id-1", "dup", "fail"],
        ["id-2", "dup", "fail"],
        ["id-3", "unique", "pass"],
    ]
    assert set(df["check_key"]) == {DUPLICATE_NAME_V2}
    assert set(df["docdb_version"]) == {"v2"}
    assert df.loc[0, "location"] == "s3://bucket/dup-1"
    assert df.loc[0, "_last_modified"] == "2026-01-01"
    assert df["checked_at"].nunique() == 1
    assert df["check_description"].str.startswith("Fails").all()
    assert df["check_source_url"].nunique() == 1
    pd.testing.assert_frame_equal(registry.BACKEND.read(registry.NAMES["record_consistency_checks"]), df)


def test_record_consistency_checks_returns_cached_table_without_force():
    cached = pd.DataFrame({"check_key": [DUPLICATE_NAME_V2], "status": ["pass"]})
    registry.BACKEND.write(registry.NAMES["record_consistency_checks"], cached)

    assert record_consistency_checks() is cached


def test_record_consistency_checks_raises_without_asset_basics():
    with pytest.raises(ValueError, match="asset_basics"):
        record_consistency_checks(force_update=True)

    assert registry.BACKEND.read(registry.NAMES["record_consistency_checks"]).empty
