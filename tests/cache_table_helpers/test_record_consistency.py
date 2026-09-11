"""Unit tests for the record-consistency checks cache table."""

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
    record_consistency_checks,
    record_consistency_checks_columns,
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

    result = record_consistency_checks(force_update=True)

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
    assert manifest["check_count"] == 1
    assert manifest["passed_count"] == 1
    assert manifest["failed_count"] == 2
    assert manifest["unknown_count"] == 0
    assert manifest["row_count"] == 3
    assert manifest["checks"] == [
        {
            "candidate_count": 3,
            "check_key": "docdb_duplicate_name_v2",
            "description": 'Fails each record in DocDB v2 whose exact "name" key is identical to another v2 record.',
            "docdb_version": "v2",
            "duplicate_group_count": 1,
            "failed_count": 2,
            "implementation_url": (
                "https://github.com/AllenNeuralDynamics/biodata-cache/blob/5b10df0/"
                "src/biodata_cache/record_consistency.py#L39"
            ),
            "parse_failure_count": 0,
            "passed_count": 1,
            "processed_count": 3,
            "skipped_count": 0,
            "unknown_count": 0,
        }
    ]


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
        result = record_consistency_checks(force_update=True)

    assert backend.read(TABLE_NAME).equals(result)
    assert json.loads(backend.get_json(MANIFEST_KEY))["complete"] is True


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_returns_cached_table_without_rebuilding_by_default(mock_backend):
    cached = _basics({"_id": "v2-a", "name": "cached", "location": None})
    mock_backend.read.return_value = cached

    result = record_consistency_checks()

    assert result is cached
    mock_backend.read.assert_called_once_with(TABLE_NAME)
    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_missing_asset_basics_fails_without_writing(mock_backend):
    mock_backend.read.side_effect = [pd.DataFrame(), pd.DataFrame()]

    with pytest.raises(ValueError, match="asset_basics cache is empty"):
        record_consistency_checks(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_invalid_asset_basics_schema_fails_without_writing(mock_backend):
    mock_backend.read.side_effect = [pd.DataFrame(), pd.DataFrame({"_id": ["v2-a"], "location": [None]})]

    with pytest.raises(ValueError, match="missing required columns"):
        record_consistency_checks(force_update=True)

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
        record_consistency_checks(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


def test_result_and_registry_columns_match():
    """The serialized output and registry metadata expose the same fields."""
    column_names = tuple(column.name for column in record_consistency_checks_columns())

    assert column_names == TABLE_COLUMNS
    assert RESULT_COLUMNS == TABLE_COLUMNS[2:]
