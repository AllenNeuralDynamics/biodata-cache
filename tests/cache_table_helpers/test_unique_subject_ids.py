"""Unit tests for unique_subject_ids cache table."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.unique_subject_ids import unique_subject_ids


@patch("aind_data_access_api.document_db.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.unique_subject_ids.registry.BACKEND")
def test_cache_hit(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame({"subject_id": ["sub001", "sub002"]})
    result = unique_subject_ids(force_update=False)
    assert result == ["sub001", "sub002"]
    mock_client_class.assert_not_called()


@patch("biodata_cache.cache_table_helpers.unique_subject_ids.registry.BACKEND")
def test_empty_cache_raises_error(mock_backend):
    mock_backend.read.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        unique_subject_ids(force_update=False)


@patch("aind_data_access_api.document_db.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.unique_subject_ids.registry.BACKEND")
def test_cache_miss(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [{"subject_id": "sub001"}, {"subject_id": "sub002"}]
    result = unique_subject_ids(force_update=True)
    assert result == ["sub001", "sub002"]
    mock_client_class.assert_called_once()


@patch("aind_data_access_api.document_db.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.unique_subject_ids.registry.BACKEND")
def test_force_update(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame({"subject_id": ["old_sub"]})
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [{"subject_id": "new_sub"}]
    result = unique_subject_ids(force_update=True)
    assert result == ["new_sub"]
