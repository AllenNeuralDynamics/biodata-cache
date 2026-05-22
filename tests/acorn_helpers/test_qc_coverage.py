"""Additional unit tests for QC acorn to improve code coverage."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import zombie_squirrel.acorns as acorns
from zombie_squirrel.acorn_helpers.qc import qc
from zombie_squirrel.forest import MemoryTree


@pytest.fixture(autouse=True)
def memory_tree():
    acorns.TREE = MemoryTree()


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_lazy_with_force_update(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-001", "name": "test-asset",
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Test Metric", "stage": "Processing",
            "modality": {"name": "Test Modality", "abbreviation": "tm"},
            "value": "pass", "tags": None,
            "status_history": [{"status": "Pass", "evaluator": "test_user", "timestamp": "2025-01-01T00:00:00"}],
        }]},
    }]
    path = qc("test-subject", force_update=True, lazy=True)
    assert isinstance(path, str)
    assert "qc/test-subject" in path


def test_qc_lazy_without_force_update():
    path = qc("test-subject", force_update=False, lazy=True)
    assert isinstance(path, str)
    assert "qc/test-subject" in path


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_columns_in_output(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-001", "name": "test-asset",
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Test Metric", "stage": "Processing",
            "modality": {"name": "Test Modality", "abbreviation": "tm"},
            "value": "pass", "tags": None, "status_history": [],
        }]},
    }]
    df = qc("test-subject", force_update=True)
    for col in ["name", "stage", "modality", "value", "asset_name", "subject_id", "timestamp"]:
        assert col in df.columns


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_drops_unwanted_columns(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-001", "name": "test-asset",
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Test Metric", "stage": "Processing",
            "modality": {"name": "Test Modality", "abbreviation": "tm"},
            "value": "pass", "tags": None, "status_history": [{"status": "Pass"}],
        }]},
    }]
    from zombie_squirrel.acorn_helpers.qc import QC_METRIC_FIELDS
    original_fields = ["name", "modality", "stage", "value", "status_history"]
    with patch("zombie_squirrel.acorn_helpers.qc.QC_METRIC_FIELDS", original_fields + ["object_type"]):
        df = qc("test-subject", force_update=True)
    assert "object_type" not in df.columns
    assert "status_history" not in df.columns
    assert "name" in df.columns


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_timestamp_parsing_with_z_suffix(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-001", "name": "test-asset",
        "acquisition": {"acquisition_start_time": "2025-01-15T10:30:45Z"},
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Test Metric", "stage": "Processing",
            "modality": {"name": "Test Modality", "abbreviation": "tm"},
            "value": "pass", "tags": None, "status_history": [],
        }]},
    }]
    df = qc("test-subject", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["timestamp"] is not None
    assert df.iloc[0]["timestamp"].year == 2025


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_timestamp_parsing_invalid_format(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-002", "name": "test-asset",
        "acquisition": {"acquisition_start_time": "invalid-timestamp"},
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Test Metric", "stage": "Processing",
            "modality": {"name": "Test Modality", "abbreviation": "tm"},
            "value": "pass", "tags": None, "status_history": [],
        }]},
    }]
    df = qc("test-subject", force_update=True)
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["timestamp"])


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_curation_metric_skipped(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-003", "name": "test-asset",
        "quality_control": {"metrics": [
            {
                "object_type": "Curation metric", "name": "Curation Metric (should be skipped)",
                "stage": "Processing", "modality": {"name": "Test Modality", "abbreviation": "tm"},
                "value": "pass", "tags": None, "status_history": [],
            },
            {
                "object_type": "QC metric", "name": "Regular Metric",
                "stage": "Processing", "modality": {"name": "Test Modality", "abbreviation": "tm"},
                "value": "pass", "tags": None, "status_history": [],
            },
        ]},
    }]
    df = qc("test-subject", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Regular Metric"
