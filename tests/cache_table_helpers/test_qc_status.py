"""Tests for the per-asset modality and stage QC status table."""

from unittest.mock import patch

import biodata_cache.registry as registry
from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers import qc_status as qc_status_module
from biodata_cache.cache_table_helpers.qc_status import qc_status


def setup_function():
    registry.BACKEND = MemoryBackend()
    qc_status_module._STATUS_COLUMN_NAMES = ()


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_status_builds_one_row_with_modality_and_stage_columns(mock_client_class):
    client = mock_client_class.return_value
    client.retrieve_docdb_records.side_effect = [
        [
            {"_id": "1", "name": "pophys_asset"},
            {"_id": "2", "name": "behavior_asset"},
            {"_id": "3", "name": "fib_missing_status"},
        ],
        [
            {
                "_id": "1",
                "name": "pophys_asset",
                "quality_control": {
                    "status": {"pophys": "Pass", "Processing": "Fail", "type:ROIs": "Fail"},
                    "metrics": [
                        {"modality": {"abbreviation": "pophys"}, "stage": "Processing"},
                    ],
                },
            },
            {
                "_id": "2",
                "name": "behavior_asset",
                "quality_control": {
                    "status": {"behavior": "Pending", "Raw data": "Pass", "type:Sync Summary": "Fail"},
                    "metrics": [
                        {"modality": "behavior", "stage": "Raw data"},
                    ],
                },
            },
            {
                "_id": "3",
                "name": "fib_missing_status",
                "quality_control": {
                    "status": {},
                    "metrics": [{"modality": {"abbreviation": "fib"}, "stage": "Analysis"}],
                },
            },
        ],
    ]

    df = qc_status(force_update=True)

    assert df.columns.tolist() == ["name", "Analysis", "behavior", "fib", "pophys", "Processing", "Raw data"]
    assert df["name"].tolist() == ["behavior_asset", "fib_missing_status", "pophys_asset"]
    assert df.loc[df["name"] == "pophys_asset", "pophys"].item() == "Pass"
    assert df.loc[df["name"] == "pophys_asset", "Processing"].item() == "Fail"
    assert df.loc[df["name"] == "behavior_asset", "behavior"].item() == "Pending"
    assert df.loc[df["name"] == "behavior_asset", "Raw data"].item() == "Pass"
    assert df.loc[df["name"] == "fib_missing_status", "fib"].isna().item()
    assert df.loc[df["name"] == "fib_missing_status", "Analysis"].isna().item()
    assert [column.name for column in qc_status_module.qc_status_columns()] == [
        "name",
        "Analysis",
        "behavior",
        "fib",
        "pophys",
        "Processing",
        "Raw data",
    ]
    assert registry.BACKEND.read("qc_status").equals(df)
    assert client.retrieve_docdb_records.call_count == 2


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_status_without_records_writes_empty_name_column(mock_client_class):
    mock_client_class.return_value.retrieve_docdb_records.return_value = []

    df = qc_status(force_update=True)

    assert df.empty
    assert df.columns.tolist() == ["name"]
    assert registry.BACKEND.read("qc_status").columns.tolist() == ["name"]


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_status_uses_latest_duplicate_asset_record(mock_client_class):
    client = mock_client_class.return_value
    client.retrieve_docdb_records.side_effect = [
        [{"_id": "old", "name": "same_asset"}, {"_id": "new", "name": "same_asset"}],
        [
            {
                "_id": "old",
                "_last_modified": "2025-01-01T00:00:00Z",
                "name": "same_asset",
                "quality_control": {
                    "status": {"pophys": "Pending", "Processing": "Pending"},
                    "metrics": [{"modality": {"abbreviation": "pophys"}, "stage": "Processing"}],
                },
            },
            {
                "_id": "new",
                "_last_modified": "2025-02-01T00:00:00Z",
                "name": "same_asset",
                "quality_control": {
                    "status": {"pophys": "Pass", "Processing": "Pass"},
                    "metrics": [{"modality": {"abbreviation": "pophys"}, "stage": "Processing"}],
                },
            },
        ],
    ]

    df = qc_status(force_update=True)

    assert len(df) == 1
    assert df.loc[0, "pophys"] == "Pass"
    assert df.loc[0, "Processing"] == "Pass"
