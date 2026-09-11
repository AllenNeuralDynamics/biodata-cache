"""Unit tests for the v2 record-consistency cache table."""

import json
from unittest.mock import patch

import pandas as pd
import pytest

from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers.record_consistency import (
    MANIFEST_KEY,
    RESULT_COLUMNS,
    TABLE_COLUMNS,
    TABLE_NAME,
    record_consistency_flags_v2,
    record_consistency_flags_v2_columns,
)


def _basics(*records: dict) -> pd.DataFrame:
    """Build a minimal asset-basics source frame."""
    return pd.DataFrame(records, columns=["_id", "name", "location"])


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_builds_flags_from_asset_basics_and_writes_completion_manifest(mock_backend):
    mock_backend.read.side_effect = [
        pd.DataFrame(),
        _basics(
            {"_id": "v2-b", "name": "same", "location": "s3://bucket/b"},
            {"_id": "v2-a", "name": "same", "location": "s3://bucket/a"},
            {"_id": "v2-c", "name": "unique", "location": "s3://bucket/c"},
        ),
    ]

    result = record_consistency_flags_v2(force_update=True)

    assert list(result.columns) == list(TABLE_COLUMNS)
    assert result["run_id"].nunique() == 1
    assert result["checked_at"].nunique() == 1
    assert result["docdb_id"].tolist() == ["v2-a", "v2-b", "v2-c"]
    assert result["status"].tolist() == ["fail", "fail", "pass"]
    mock_backend.write.assert_called_once_with(TABLE_NAME, result)
    mock_backend.put_json.assert_called_once()
    manifest_key, manifest_text = mock_backend.put_json.call_args.args
    assert manifest_key == MANIFEST_KEY
    manifest = json.loads(manifest_text)
    assert manifest["complete"] is True
    assert manifest["check_key"] == "docdb_duplicate_name_v2"
    assert manifest["docdb_version"] == "v2"
    assert manifest["candidate_count"] == 3
    assert manifest["failed_count"] == 2
    assert manifest["duplicate_group_count"] == 1
    assert manifest["row_count"] == 3


def test_builder_round_trips_through_memory_backend():
    backend = MemoryBackend()
    backend.write(
        "asset_basics",
        _basics(
            {"_id": "v2-b", "name": "same", "location": "s3://bucket/b"},
            {"_id": "v2-a", "name": "same", "location": "s3://bucket/a"},
        ),
    )

    with patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND", backend):
        result = record_consistency_flags_v2(force_update=True)

    assert backend.read(TABLE_NAME).equals(result)
    assert json.loads(backend.get_json(MANIFEST_KEY))["complete"] is True


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_returns_cached_table_without_rebuilding_by_default(mock_backend):
    cached = _basics({"_id": "v2-a", "name": "cached", "location": None})
    mock_backend.read.return_value = cached

    result = record_consistency_flags_v2()

    assert result is cached
    mock_backend.read.assert_called_once_with(TABLE_NAME)
    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_missing_asset_basics_fails_without_writing(mock_backend):
    mock_backend.read.side_effect = [pd.DataFrame(), pd.DataFrame()]

    with pytest.raises(ValueError, match="asset_basics cache is empty"):
        record_consistency_flags_v2(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_invalid_asset_basics_schema_fails_without_writing(mock_backend):
    mock_backend.read.side_effect = [pd.DataFrame(), pd.DataFrame({"_id": ["v2-a"], "location": [None]})]

    with pytest.raises(ValueError, match="missing required columns"):
        record_consistency_flags_v2(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_incomplete_classification_preserves_previous_result(mock_backend):
    mock_backend.read.side_effect = [
        pd.DataFrame(),
        _basics(
            {"_id": "v2-good", "name": "same", "location": None},
            {"_id": "v2-bad", "name": 7, "location": None},
        ),
    ]

    with pytest.raises(ValueError, match="parse failures"):
        record_consistency_flags_v2(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


def test_result_and_registry_columns_match():
    """The serialized output and registry metadata expose the same fields."""
    column_names = tuple(column.name for column in record_consistency_flags_v2_columns())

    assert column_names == TABLE_COLUMNS
    assert RESULT_COLUMNS == TABLE_COLUMNS[2:]
