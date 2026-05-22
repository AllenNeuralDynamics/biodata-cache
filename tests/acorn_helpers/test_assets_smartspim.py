"""Unit tests for assets_smartspim acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.assets_smartspim import (
    _build_rows,
    _fetch_asset_metadata,
    _list_channels,
    _quantification_link,
    _segmentation_link,
    _stitched_link,
    assets_smartspim,
    assets_smartspim_columns,
)

LOCATION = "s3://aind-open-data/SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"

EXAMPLE_RECORD = {
    "_id": "abc123",
    "name": "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00",
    "location": LOCATION,
    "subject": {"subject_id": "123456", "subject_details": {"genotype": "wt/wt"}},
    "data_description": {"institution": {"abbreviation": "AIBS"}},
    "acquisition": {"acquisition_start_time": "2026-01-01T00:00:00"},
    "processing": {"data_processes": [{"end_date_time": "2026-01-01T10:00:00"}, {"end_date_time": "2026-01-02T12:00:00"}]},
}


# --- Link helpers ---

def test_stitched_link():
    assert _stitched_link(LOCATION) == f"https://allen.neuroglass.io/new#!{LOCATION}/neuroglancer_config.json"

def test_segmentation_link():
    assert _segmentation_link(LOCATION, "Ex_561_Em_600") == (
        f"https://allen.neuroglass.io/new#!{LOCATION}/image_cell_segmentation/Ex_561_Em_600/visualization/neuroglancer_config.json"
    )

def test_quantification_link():
    assert _quantification_link(LOCATION, "Ex_561_Em_600") == (
        f"https://allen.neuroglass.io/new#!{LOCATION}/image_cell_quantification/Ex_561_Em_600/visualization/neuroglancer_config.json"
    )


# --- _list_channels ---

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.boto3.client")
def test_list_channels_returns_channel_names(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.list_objects_v2.return_value = {
        "CommonPrefixes": [
            {"Prefix": "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00/image_cell_segmentation/Ex_488_Em_525/"},
            {"Prefix": "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00/image_cell_segmentation/Ex_561_Em_600/"},
        ]
    }
    result = _list_channels(LOCATION)
    assert result == ["Ex_488_Em_525", "Ex_561_Em_600"]
    mock_s3.list_objects_v2.assert_called_once_with(
        Bucket="aind-open-data",
        Prefix="SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00/image_cell_segmentation/",
        Delimiter="/",
    )

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.boto3.client")
def test_list_channels_returns_empty_when_no_prefixes(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.list_objects_v2.return_value = {}
    assert _list_channels(LOCATION) == []


# --- _fetch_asset_metadata ---

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.MetadataDbClient")
def test_fetch_asset_metadata_returns_dict_keyed_by_name(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [EXAMPLE_RECORD]
    result = _fetch_asset_metadata(["SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"])
    assert "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00" in result
    assert result["SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"]["_id"] == "abc123"

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.MetadataDbClient")
def test_fetch_asset_metadata_passes_correct_filter(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = []
    names = ["asset_a", "asset_b"]
    _fetch_asset_metadata(names)
    call_kwargs = mock_client.retrieve_docdb_records.call_args[1]
    assert call_kwargs["filter_query"] == {"name": {"$in": names}}

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.MetadataDbClient")
def test_fetch_asset_metadata_batches_large_requests(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = []
    _fetch_asset_metadata([f"asset_{i}" for i in range(250)])
    assert mock_client.retrieve_docdb_records.call_count == 3


# --- _build_rows ---

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_one_row_per_asset_with_channel_columns(mock_list_channels):
    mock_list_channels.return_value = ["Ex_488_Em_525", "Ex_561_Em_600"]
    raw_name = "SmartSPIM_123_2026-01-01_00-00-00"
    stitched_name = "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"
    rows = _build_rows({raw_name: stitched_name}, {stitched_name: EXAMPLE_RECORD})
    assert len(rows) == 1
    assert rows[0]["channel_1"] == "Ex_488_Em_525"
    assert rows[0]["channel_2"] == "Ex_561_Em_600"
    assert rows[0]["channel_3"] is None

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_processed_row_fields_populated(mock_list_channels):
    mock_list_channels.return_value = ["Ex_561_Em_600"]
    raw_name = "SmartSPIM_123_2026-01-01_00-00-00"
    stitched_name = "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"
    row = _build_rows({raw_name: stitched_name}, {stitched_name: EXAMPLE_RECORD})[0]
    assert row["subject_id"] == "123456"
    assert row["genotype"] == "wt/wt"
    assert row["institution"] == "AIBS"
    assert row["acquisition_start_time"] == "2026-01-01T00:00:00"
    assert row["processing_end_time"] == "2026-01-02T12:00:00"
    assert row["stitched_link"] == _stitched_link(LOCATION)
    assert row["channel_1"] == "Ex_561_Em_600"
    assert row["segmentation_link_1"] == _segmentation_link(LOCATION, "Ex_561_Em_600")
    assert row["quantification_link_1"] == _quantification_link(LOCATION, "Ex_561_Em_600")
    assert row["channel_2"] is None
    assert row["segmentation_link_2"] is None
    assert row["quantification_link_2"] is None
    assert row["processed"] is True
    assert row["name"] == stitched_name

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_unprocessed_row_has_no_links(mock_list_channels):
    raw_name = "SmartSPIM_123_2026-01-01_00-00-00"
    raw_record = {
        "name": raw_name,
        "subject": {"subject_id": "123456", "subject_details": {"genotype": "wt/wt"}},
        "data_description": {"institution": {"abbreviation": "AIBS"}},
        "acquisition": {"acquisition_start_time": "2026-01-01T00:00:00"},
    }
    row = _build_rows({raw_name: None}, {raw_name: raw_record})[0]
    assert row["subject_id"] == "123456"
    assert row["acquisition_start_time"] == "2026-01-01T00:00:00"
    assert row["processing_end_time"] is None
    assert row["stitched_link"] is None
    assert row["processed"] is False
    assert row["name"] == raw_name
    mock_list_channels.assert_not_called()
    for i in range(1, 4):
        assert row[f"channel_{i}"] is None
        assert row[f"segmentation_link_{i}"] is None
        assert row[f"quantification_link_{i}"] is None

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_no_channels_produces_null_channel_columns(mock_list_channels):
    mock_list_channels.return_value = []
    raw_name = "SmartSPIM_123_2026-01-01_00-00-00"
    stitched_name = "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"
    rows = _build_rows({raw_name: stitched_name}, {stitched_name: EXAMPLE_RECORD})
    assert len(rows) == 1
    for i in range(1, 4):
        assert rows[0][f"channel_{i}"] is None
        assert rows[0][f"segmentation_link_{i}"] is None
        assert rows[0][f"quantification_link_{i}"] is None

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_uses_last_data_process_end_time(mock_list_channels):
    mock_list_channels.return_value = []
    raw_name = "SmartSPIM_123_2026-01-01_00-00-00"
    stitched_name = "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"
    record = {**EXAMPLE_RECORD, "processing": {"data_processes": [
        {"end_date_time": "2026-01-01T10:00:00"}, {"end_date_time": "2026-01-02T12:00:00"}
    ]}}
    rows = _build_rows({raw_name: stitched_name}, {stitched_name: record})
    assert rows[0]["processing_end_time"] == "2026-01-02T12:00:00"

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_no_data_processes_gives_null_end_time(mock_list_channels):
    mock_list_channels.return_value = []
    raw_name = "SmartSPIM_123_2026-01-01_00-00-00"
    stitched_name = "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"
    record = {**EXAMPLE_RECORD, "processing": {"data_processes": []}}
    rows = _build_rows({raw_name: stitched_name}, {stitched_name: record})
    assert rows[0]["processing_end_time"] is None


# --- assets_smartspim ---

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_cache_hit_returns_cached_df(mock_tree):
    cached_df = pd.DataFrame({"name": ["asset_a"], "channel": ["Ex_561_Em_600"]})
    mock_tree.scurry.return_value = cached_df
    result = assets_smartspim(force_update=False)
    assert len(result) == 1
    mock_tree.hide.assert_not_called()

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_empty_cache_raises_without_force_update(mock_tree):
    mock_tree.scurry.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        assets_smartspim(force_update=False)

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._build_rows")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_asset_metadata")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.source_data")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.asset_basics")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_force_update_builds_and_caches(mock_tree, mock_asset_basics, mock_source_data, mock_fetch_meta, mock_build_rows):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_asset_basics.return_value = pd.DataFrame({"data_level": ["raw"], "modalities": ["SPIM"], "name": ["SmartSPIM_raw_2026-01-01_00-00-00"]})
    mock_source_data.return_value = pd.DataFrame({
        "name": ["SmartSPIM_raw_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"],
        "source_data": ["SmartSPIM_raw_2026-01-01_00-00-00"],
        "pipeline_name": ["stitching"],
        "processing_time": ["2026-01-02_00-00-00"],
    })
    mock_fetch_meta.return_value = {}
    mock_build_rows.return_value = [{"name": "SmartSPIM_raw_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00", "processed": True}]
    result = assets_smartspim(force_update=True)
    assert len(result) == 1
    mock_tree.hide.assert_called_once()

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.source_data")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.asset_basics")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_unprocessed_assets_included_with_processed_false(mock_tree, mock_asset_basics, mock_source_data):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_asset_basics.return_value = pd.DataFrame({"data_level": ["raw"], "modalities": ["SPIM"], "name": ["SmartSPIM_raw_2026-01-01_00-00-00"]})
    mock_source_data.return_value = pd.DataFrame({
        "name": ["SmartSPIM_raw_2026-01-01_00-00-00_processed_2026-01-02_00-00-00"],
        "source_data": ["SmartSPIM_raw_2026-01-01_00-00-00"],
        "pipeline_name": ["processing"],
        "processing_time": ["2026-01-02_00-00-00"],
    })
    with patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_asset_metadata", return_value={}):
        with patch("zombie_squirrel.acorn_helpers.assets_smartspim._build_rows", return_value=[{"name": "SmartSPIM_raw_2026-01-01_00-00-00", "processed": False}]) as mock_build:
            assets_smartspim(force_update=True)
    raw_to_stitched_arg = mock_build.call_args[0][0]
    assert "SmartSPIM_raw_2026-01-01_00-00-00" in raw_to_stitched_arg
    assert raw_to_stitched_arg["SmartSPIM_raw_2026-01-01_00-00-00"] is None
    mock_tree.hide.assert_called_once()

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.source_data")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.asset_basics")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_filters_only_raw_spim_assets(mock_tree, mock_asset_basics, mock_source_data):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_asset_basics.return_value = pd.DataFrame({
        "data_level": ["raw", "raw", "derived"],
        "modalities": ["SPIM", "ECEPHYS", "SPIM"],
        "name": ["spim_raw", "ecephys_raw", "spim_derived"],
    })
    mock_source_data.return_value = pd.DataFrame({
        "name": ["spim_raw_stitched_2026-01-02_00-00-00", "ecephys_raw_derived", "spim_derived_stitched"],
        "source_data": ["spim_raw", "ecephys_raw", "spim_derived"],
        "pipeline_name": ["stitching", "pipeline", "stitching"],
        "processing_time": ["2026-01-02_00-00-00", "2026-01-02_00-00-00", "2026-01-02_00-00-00"],
    })
    with patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_asset_metadata", return_value={}):
        with patch("zombie_squirrel.acorn_helpers.assets_smartspim._build_rows", return_value=[]) as mock_build:
            assets_smartspim(force_update=True)
    raw_to_stitched_arg = mock_build.call_args[0][0]
    assert "spim_raw" in raw_to_stitched_arg
    assert "ecephys_raw" not in raw_to_stitched_arg
    assert "spim_derived" not in raw_to_stitched_arg


# --- assets_smartspim_columns ---

def test_returns_expected_columns():
    assert [col.name for col in assets_smartspim_columns()] == [
        "subject_id", "genotype", "institution", "acquisition_start_time", "processing_end_time",
        "stitched_link", "processed", "name",
        "channel_1", "segmentation_link_1", "quantification_link_1",
        "channel_2", "segmentation_link_2", "quantification_link_2",
        "channel_3", "segmentation_link_3", "quantification_link_3",
    ]
