"""Additional unit tests for QC cache table to improve code coverage."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers.qc import qc


@pytest.fixture(autouse=True)
def memory_backend():
    registry.BACKEND = MemoryBackend()


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_lazy_with_force_update(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [
                            {"status": "Pass", "evaluator": "test_user", "timestamp": "2025-01-01T00:00:00"}
                        ],
                    }
                ]
            },
        }
    ]
    path = qc("test-asset", force_update=True, lazy=True)
    assert isinstance(path, str)
    assert "qc/raw_asset_name=test-asset" in path


def test_qc_lazy_without_force_update():
    path = qc("test-asset", force_update=False, lazy=True)
    assert isinstance(path, str)
    assert "qc/raw_asset_name=test-asset" in path


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_columns_in_output(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass"}],
                    }
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    for col in ["name", "stage", "modality", "value", "asset_name", "subject_id", "timestamp"]:
        assert col in df.columns


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_does_not_store_status_history_but_keeps_metric_metadata(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass"}],
                    }
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert "object_type" in df.columns
    assert "status_history" not in df.columns
    assert "name" in df.columns


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_timestamp_parsing_with_z_suffix(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "acquisition": {"acquisition_start_time": "2025-01-15T10:30:45Z"},
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass"}],
                    }
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["timestamp"] is not None
    assert df.iloc[0]["timestamp"].year == 2025


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_timestamp_parsing_invalid_format(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-002",
            "name": "test-asset",
            "acquisition": {"acquisition_start_time": "invalid-timestamp"},
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass"}],
                    }
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["timestamp"])


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_curation_metric_is_preserved(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-003",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "Curation metric",
                        "name": "Curation Metric (should be skipped)",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass"}],
                    },
                    {
                        "object_type": "QC metric",
                        "name": "Regular Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass"}],
                    },
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert len(df) == 2
    assert set(df["name"]) == {"Curation Metric (should be skipped)", "Regular Metric"}
