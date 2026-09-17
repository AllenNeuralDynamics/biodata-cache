"""Unit tests for the record-consistency checks cache table."""

import json
from types import SimpleNamespace
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


@pytest.fixture
def mock_cross_service_sources():
    """Avoid live S3 and Code Ocean calls in cache-builder tests."""
    with (
        patch(
            "biodata_cache.cache_table_helpers.record_consistency._list_open_data_prefixes",
            return_value=[],
        ) as prefixes,
        patch(
            "biodata_cache.cache_table_helpers.record_consistency._fetch_external_code_ocean_assets",
            return_value=[],
        ) as assets,
    ):
        yield prefixes, assets


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_builds_all_flags_and_writes_completion_manifest(mock_backend, mock_v1_records, mock_cross_service_sources):
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
    assert manifest["check_count"] == 3
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
            "description": "Fails every DocDB v1 record whose non-empty `name` has zero exact matches in DocDB v2.",
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
        {
            "candidate_count": 0,
            "check_key": "s3_open_data_prefix_code_ocean_external_asset",
            "description": (
                "Fails each top-level `aind-open-data` S3 prefix with visible exact-name Code Ocean assets when "
                "none externally references that exact bucket and prefix."
            ),
            "docdb_version": None,
            "failed_count": 0,
            "implementation_url": (
                "https://github.com/AllenNeuralDynamics/biodata-cache/blob/"
                "codex/record-consistency-open-data-code-ocean/src/biodata_cache/record_consistency.py#L272"
            ),
            "parse_failure_count": 0,
            "passed_count": 0,
            "processed_count": 0,
            "skipped_count": 0,
            "unknown_count": 0,
        },
    ]


@patch("biodata_cache.cache_table_helpers.record_consistency.registry.BACKEND")
def test_appends_cross_service_results_to_shared_table(mock_backend, mock_v1_records, mock_cross_service_sources):
    """The S3/Code Ocean check reuses the generic consistency table contract."""
    prefixes, assets = mock_cross_service_sources
    mock_backend.read.side_effect = [
        pd.DataFrame(),
        _basics({"_id": "v2-a", "name": "asset-a", "location": "s3://aind-open-data/asset-a"}),
    ]
    prefixes.return_value = ["asset-a/", "asset-b/"]
    assets.return_value = [{"name": "asset-a", "bucket": "aind-open-data", "prefix": "asset-a", "external": True}]

    result = record_consistency_checks(force_update=True)

    cross_service = result[result["check_key"] == "s3_open_data_prefix_code_ocean_external_asset"]
    assert cross_service["name"].tolist() == ["asset-a", "asset-b"]
    assert cross_service["status"].tolist() == ["pass", "unknown"]
    assert cross_service["docdb_id"].isna().all()


@patch("boto3.client")
def test_lists_every_public_top_level_s3_prefix_anonymously(mock_boto_client):
    """S3 collection uses root delimiter pagination and unsigned requests."""
    from botocore import UNSIGNED

    from biodata_cache.cache_table_helpers.record_consistency import _list_open_data_prefixes

    paginator = mock_boto_client.return_value.get_paginator.return_value
    paginator.paginate.return_value = [
        {"CommonPrefixes": [{"Prefix": "asset-b/"}]},
        {"CommonPrefixes": [{"Prefix": "asset-a/"}]},
    ]

    assert _list_open_data_prefixes() == ["asset-a/", "asset-b/"]
    assert mock_boto_client.call_args.kwargs["config"].signature_version == UNSIGNED
    mock_boto_client.return_value.get_paginator.assert_called_once_with("list_objects_v2")
    paginator.paginate.assert_called_once_with(Bucket="aind-open-data", Delimiter="/")


@patch.dict("os.environ", {"CUSTOM_KEY": "secret"}, clear=False)
@patch("codeocean.CodeOcean")
def test_fetches_paginated_external_code_ocean_catalog(mock_client_class):
    """Code Ocean collection delegates pagination to one external-asset sweep."""
    from codeocean.data_asset import DataAssetSearchOrigin

    from biodata_cache.cache_table_helpers.record_consistency import _fetch_external_code_ocean_assets

    source = SimpleNamespace(bucket="aind-open-data", prefix="asset-a", external=True)
    mock_client_class.return_value.data_assets.search_data_assets_iterator.return_value = iter(
        [SimpleNamespace(id="co-a", name="asset-a", source_bucket=source)]
    )

    assert _fetch_external_code_ocean_assets() == [
        {
            "id": "co-a",
            "name": "asset-a",
            "bucket": "aind-open-data",
            "prefix": "asset-a",
            "external": True,
        }
    ]
    mock_client_class.assert_called_once_with(
        domain="https://codeocean.allenneuraldynamics.org",
        token="secret",
        retries=3,
    )
    params = mock_client_class.return_value.data_assets.search_data_assets_iterator.call_args.args[0]
    assert params.origin == DataAssetSearchOrigin.External
    assert params.archived is False
    assert params.limit == 1000


@patch.dict("os.environ", {}, clear=True)
def test_code_ocean_catalog_requires_explicit_token():
    """The cross-service check fails closed when authentication is absent."""
    from biodata_cache.cache_table_helpers.record_consistency import _fetch_external_code_ocean_assets

    with pytest.raises(ValueError, match="CUSTOM_KEY is required"):
        _fetch_external_code_ocean_assets()


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


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_retries_v1_sweep_after_pagination_repeats_id(mock_client_class):
    from biodata_cache.cache_table_helpers.record_consistency import _fetch_v1_records

    duplicate_sweep = [
        {"_id": "v1-a", "name": "a", "location": None},
        {"_id": "v1-a", "name": "a", "location": None},
    ]
    clean_sweep = [{"_id": "v1-a", "name": "a", "location": None}]
    retrieve = mock_client_class.return_value.retrieve_docdb_records
    retrieve.side_effect = [duplicate_sweep, clean_sweep]

    assert _fetch_v1_records() == clean_sweep
    assert retrieve.call_count == 2


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_rejects_repeated_ids_after_bounded_v1_sweep_retries(mock_client_class):
    from biodata_cache.cache_table_helpers.record_consistency import _fetch_v1_records

    duplicate_sweep = [
        {"_id": "v1-a", "name": "a", "location": None},
        {"_id": "v1-a", "name": "a", "location": None},
    ]
    retrieve = mock_client_class.return_value.retrieve_docdb_records
    retrieve.return_value = duplicate_sweep

    with pytest.raises(ValueError, match="remained inconsistent after 3 attempts"):
        _fetch_v1_records()

    assert retrieve.call_count == 3


def test_builder_round_trips_through_memory_backend(mock_v1_records, mock_cross_service_sources):
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
