"""Unit tests for QC acorn."""

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
def test_qc_cache_miss_with_force_update(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-001",
        "name": "test-asset",
        "quality_control": {"metrics": [
            {
                "object_type": "QC metric", "name": "Test Metric 1", "stage": "Processing",
                "modality": {"name": "Test Modality", "abbreviation": "tm"},
                "value": {"value": "pass", "status": "Pass"}, "tags": {"tag1": "value1"},
                "status_history": [{"status": "Pass", "evaluator": "test_user", "timestamp": "2025-01-01T00:00:00"}],
            },
            {
                "object_type": "QC metric", "name": "Test Metric 2", "stage": "Acquisition",
                "modality": {"name": "Test Modality 2", "abbreviation": "tm2"},
                "value": None, "tags": None,
                "status_history": [{"status": "Pending", "evaluator": "Pending review", "timestamp": "2025-01-01T00:00:00"}],
            },
        ]},
    }]
    df = qc("test-asset", force_update=True)
    assert len(df) == 2
    assert df.iloc[0]["name"] == "Test Metric 1"
    assert df.iloc[1]["name"] == "Test Metric 2"
    assert df.iloc[0]["value"] == "{dict}"


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_cache_hit(mock_client_class):
    cache_df = pd.DataFrame({"name": ["Metric 1", "Metric 2"], "stage": ["Processing", "Acquisition"], "value": ["pass", "{dict}"]})
    acorns.TREE.hide("qc/cached-asset", cache_df)
    df = qc("cached-asset", force_update=False)
    assert len(df) == 2
    assert df.iloc[0]["name"] == "Metric 1"
    mock_client_class.assert_not_called()


def test_qc_empty_cache_raises_error():
    df = qc("nonexistent-asset", force_update=False)
    assert df.empty


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_no_record_found(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = []
    assert qc("missing-asset", force_update=True).empty


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_no_metrics_in_record(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{"_id": "test-asset-002", "name": "test-asset", "quality_control": {}}]
    assert qc("test-asset", force_update=True).empty


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_dict_value_replaced_and_no_tags_column(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-003", "name": "test-asset",
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Complex Metric", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"},
            "value": {"nested": {"deep": "value"}, "status": "Pass"},
            "tags": {"key1": "val1", "key2": "val2"}, "status_history": [],
        }]},
    }]
    df = qc("test-asset", force_update=True)
    assert df.iloc[0]["value"] == "{dict}"
    assert "tags" not in df.columns


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_cache_persistence(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-004", "name": "test-asset",
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Persistent Metric", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"}, "value": "test_value", "tags": None, "status_history": [],
        }]},
    }]
    df1 = qc("test-asset", force_update=True)
    assert len(df1) == 1
    mock_client_instance.retrieve_docdb_records.reset_mock()
    df2 = qc("test-asset", force_update=False)
    assert len(df2) == 1
    assert df2.iloc[0]["name"] == "Persistent Metric"
    mock_client_instance.retrieve_docdb_records.assert_not_called()


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_multiple_assets_merge(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {"_id": "asset1", "name": "asset1", "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Metric A", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"}, "value": "pass", "tags": None, "status_history": [],
        }]}},
        {"_id": "asset2", "name": "asset2", "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Metric B", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"}, "value": "fail", "tags": None, "status_history": [],
        }]}},
    ]
    df = qc("test-subject", asset_names=["asset1", "asset2"], force_update=True)
    assert len(df) == 2
    assert "asset_name" in df.columns
    assert df[df["name"] == "Metric A"].iloc[0]["asset_name"] == "asset1"
    assert df[df["name"] == "Metric B"].iloc[0]["asset_name"] == "asset2"


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_multiple_assets_from_cache(mock_client_class):
    cache_df1 = pd.DataFrame({"name": ["Metric 1"], "stage": ["Processing"], "value": ["pass"], "asset_name": ["asset1"]})
    cache_df2 = pd.DataFrame({"name": ["Metric 2"], "stage": ["Acquisition"], "value": ["fail"], "asset_name": ["asset2"]})
    acorns.TREE.hide("qc/test-subject", pd.concat([cache_df1, cache_df2], ignore_index=True))
    df = qc("test-subject", asset_names=["asset1", "asset2"], force_update=False)
    assert len(df) == 2
    assert "asset_name" in df.columns
    assert sorted(df["asset_name"].unique().tolist()) == ["asset1", "asset2"]
    mock_client_class.assert_not_called()


def test_qc_multiple_empty_assets_no_force_update():
    df = qc("nonexistent-subject", asset_names=["nonexistent1", "nonexistent2"], force_update=False)
    assert df.empty


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_single_asset_name_string(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {"_id": "asset1", "name": "asset1", "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Metric A", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"}, "value": "pass", "tags": None, "status_history": [],
        }]}},
        {"_id": "asset2", "name": "asset2", "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Metric B", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"}, "value": "fail", "tags": None, "status_history": [],
        }]}},
    ]
    df = qc("test-subject", asset_names="asset1", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Metric A"
    assert df.iloc[0]["asset_name"] == "asset1"


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_missing_asset_names(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {"_id": "asset1", "name": "asset1", "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Metric A", "stage": "Processing",
            "modality": {"name": "Test", "abbreviation": "t"}, "value": "pass", "tags": None, "status_history": [],
        }]}},
    ]
    df = qc("test-subject", asset_names=["asset1", "nonexistent"], force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Metric A"


@patch("zombie_squirrel.acorn_helpers.qc.MetadataDbClient")
def test_qc_numeric_value_converted_to_string(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [{
        "_id": "test-asset-001", "name": "test-asset",
        "quality_control": {"metrics": [{
            "object_type": "QC metric", "name": "Numeric Metric", "stage": "Processing",
            "modality": None, "value": 42, "tags": None, "status_history": [],
        }]},
    }]
    df = qc("test-asset", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["value"] == "42"
