"""Unit tests for the record-consistency checks cache table."""

import json
from unittest.mock import patch

import pandas as pd
import pytest

import biodata_cache.registry as registry
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


@pytest.fixture
def mock_v1_records():
    """Avoid live DocDB calls and expose the v1 source to each test."""
    with patch(
        "biodata_cache.cache_table_helpers.record_consistency._fetch_v1_records",
        return_value=[],
    ) as mocked:
        yield mocked


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_builds_all_flags_and_writes_completion_manifest(mock_backend, mock_v1_records):
    mock_backend.read.side_effect = [
        pd.DataFrame(),
        _basics(
            {"_id": "v2-b", "name": "same", "location": "s3://bucket/b"},
            {"_id": "v2-a", "name": "same", "location": "s3://bucket/a"},
            {"_id": "v2-c", "name": "unique", "location": "s3://bucket/c"},
        ),
    ]
    mock_v1_records.return_value = [
        {"_id": "v1-b", "name": "legacy", "location": "s3://bucket/legacy"},
        {"_id": "v1-a", "name": "same", "location": "s3://bucket/a"},
    ]

    result = record_consistency_checks(force_update=True)

    assert list(result.columns) == list(TABLE_COLUMNS)
    assert result["run_id"].nunique() == 1
    assert result["checked_at"].nunique() == 1
    assert result["docdb_id"].tolist() == ["v2-a", "v2-b", "v2-c", "v1-b", "v1-a"]
    assert result["status"].tolist() == ["fail", "fail", "pass", "fail", "pass"]
    assert result.loc[result["docdb_id"] == "v1-b", "location"].item() == "s3://bucket/legacy"
    mock_backend.write.assert_called_once_with(TABLE_NAME, result)
    mock_backend.put_json.assert_called_once()
    manifest_key, manifest_text = mock_backend.put_json.call_args.args
    assert manifest_key == MANIFEST_KEY
    manifest = json.loads(manifest_text)
    assert manifest["complete"] is True
    assert manifest["check_count"] == 2
    assert manifest["passed_count"] == 2
    assert manifest["failed_count"] == 3
    assert manifest["unknown_count"] == 0
    assert manifest["row_count"] == 5
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
        },
        {
            "candidate_count": 2,
            "check_key": "docdb_v1_name_missing_in_v2",
            "description": 'Fails each DocDB v1 record whose exact "name" has no matches in DocDB v2.',
            "docdb_version": "v1",
            "failed_count": 1,
            "implementation_url": (
                "https://github.com/AllenNeuralDynamics/biodata-cache/blob/bde9c5e/"
                "src/biodata_cache/record_consistency.py#L170"
            ),
            "parse_failure_count": 0,
            "passed_count": 1,
            "processed_count": 2,
            "skipped_count": 0,
            "unknown_count": 0,
        },
    ]


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_fetches_complete_v1_projection(mock_client_class):
    from biodata_cache.cache_table_helpers.record_consistency import _fetch_v1_records

    expected = [{"_id": "v1-a", "name": "name", "location": "s3://bucket/name"}]
    mock_client_class.return_value.retrieve_docdb_records.return_value = expected

    assert _fetch_v1_records() == expected
    mock_client_class.assert_called_once_with(host=registry.API_GATEWAY_HOST, version="v1")
    mock_client_class.return_value.retrieve_docdb_records.assert_called_once_with(
        filter_query={},
        projection={"_id": 1, "name": 1, "location": 1},
        sort={"_id": 1},
        limit=0,
    )


def test_builder_round_trips_through_memory_backend(mock_v1_records):
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
def test_incomplete_v1_classification_preserves_previous_result(mock_backend, mock_v1_records):
    mock_backend.read.side_effect = [
        pd.DataFrame(),
        _basics({"_id": "v2-a", "name": "valid", "location": None}),
    ]
    mock_v1_records.return_value = [{"_id": "v1-bad", "name": 7, "location": None}]

    with pytest.raises(ValueError, match="incomplete v1-name coverage"):
        record_consistency_checks(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_v1_retrieval_failure_preserves_previous_result(mock_backend, mock_v1_records):
    mock_backend.read.side_effect = [
        pd.DataFrame(),
        _basics({"_id": "v2-a", "name": "valid", "location": None}),
    ]
    mock_v1_records.side_effect = RuntimeError("pagination failed")

    with pytest.raises(RuntimeError, match="pagination failed"):
        record_consistency_checks(force_update=True)

    mock_backend.write.assert_not_called()
    mock_backend.put_json.assert_not_called()


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
