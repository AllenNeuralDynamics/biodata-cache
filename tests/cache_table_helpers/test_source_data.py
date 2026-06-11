"""Unit tests for source_data cache table."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from biodata_cache.cache_table_helpers.source_data import source_data


@patch("biodata_cache.cache_table_helpers.source_data.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.source_data.registry.BACKEND")
def test_source_data_cache_hit(mock_backend, mock_client_class):
    cached_df = pd.DataFrame(
        {
            "name": ["derived1", "derived2"],
            "source_data": ["raw1", "raw2"],
            "pipeline_name": ["pipeline_a", "pipeline_b"],
            "processing_time": ["2026-01-01_00-00-00", "2026-01-02_00-00-00"],
        }
    )
    mock_backend.read.return_value = cached_df
    result = source_data(force_update=False)
    assert len(result) == 2
    assert result.iloc[0]["source_data"] == "raw1"
    mock_client_class.assert_not_called()


@patch("biodata_cache.cache_table_helpers.source_data.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.source_data.registry.BACKEND")
def test_source_data_empty_cache_fetches_from_db(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = []
    result = source_data(force_update=False)
    assert isinstance(result, pd.DataFrame)
    mock_client_instance.retrieve_docdb_records.assert_called_once()


@patch("biodata_cache.cache_table_helpers.source_data.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.source_data.registry.BACKEND")
def test_source_data_cache_miss(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance

    resources_path = Path(__file__).parent.parent / "resources"
    with open(resources_path / "v2_derived.json") as f:
        derived_record = json.load(f)

    mock_client_instance.retrieve_docdb_records.return_value = [derived_record]
    result = source_data(force_update=True)

    assert len(result) > 0
    assert "name" in result.columns
    assert "source_data" in result.columns
    assert "pipeline_name" in result.columns
    assert "processing_time" in result.columns

    row = result[result["name"] == derived_record["name"]]
    assert len(row) > 0
    expected_source = derived_record["data_description"]["source_data"][0]
    assert expected_source in row["source_data"].values
    assert row.iloc[0]["processing_time"] == "2026-02-14_12-44-45"


@patch("biodata_cache.cache_table_helpers.source_data.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.source_data.registry.BACKEND")
def test_source_data_multiple_sources(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "name": "subject_2026-01-01_00-00-00_processed_2026-01-02_12-00-00",
            "data_description": {"source_data": ["src1", "src2"]},
            "processing": {"pipelines": [{"name": "my_pipeline"}]},
        }
    ]
    result = source_data(force_update=True)
    assert len(result) == 2
    assert set(result["source_data"].tolist()) == {"src1", "src2"}
    assert (result["pipeline_name"] == "my_pipeline").all()
    assert (result["processing_time"] == "2026-01-02_12-00-00").all()


@patch("biodata_cache.cache_table_helpers.source_data.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.source_data.registry.BACKEND")
def test_source_data_no_source_data(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "name": "derived_2026-01-01_00-00-00",
            "data_description": {"source_data": []},
            "processing": {"pipelines": []},
        }
    ]
    result = source_data(force_update=True)
    assert len(result) == 1
    assert result.iloc[0]["source_data"] == ""
    assert result.iloc[0]["pipeline_name"] == ""


@patch("biodata_cache.cache_table_helpers.source_data.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.source_data.registry.BACKEND")
def test_source_data_force_update(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame(
        {
            "name": ["old_derived"],
            "source_data": ["old_raw"],
            "pipeline_name": ["old_pipeline"],
            "processing_time": ["2025-01-01_00-00-00"],
        }
    )
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "name": "new_derived_2026-01-01_12-00-00",
            "data_description": {"source_data": ["new_raw"]},
            "processing": {"pipelines": [{"name": "new_pipeline"}]},
        }
    ]
    result = source_data(force_update=True)
    assert len(result) == 1
    assert result.iloc[0]["name"] == "new_derived_2026-01-01_12-00-00"
    assert result.iloc[0]["source_data"] == "new_raw"
