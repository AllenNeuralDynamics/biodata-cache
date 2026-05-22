"""Unit tests for assets_smartspim acorn."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.assets_smartspim import (
    _build_rows,
    _fetch_asset_metadata,
    _fetch_raw_ng_link,
    _list_channels,
    _quantification_link,
    _segmentation_link,
    _stitched_link,
    assets_smartspim,
    assets_smartspim_columns,
)

LOCATION = "s3://aind-open-data/SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"
RAW_NAME = "SmartSPIM_123_2026-01-01_00-00-00"
STITCHED_NAME = "SmartSPIM_123_2026-01-01_00-00-00_stitched_2026-01-02_00-00-00"

EXAMPLE_RECORD = {
    "_id": "abc123",
    "name": STITCHED_NAME,
    "location": LOCATION,
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


# --- _fetch_raw_ng_link ---

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.boto3.client")
def test_fetch_raw_ng_link_returns_link(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    ng_link = "https://allen.neuroglass.io/new#!s3://aind-open-data/SmartSPIM_123_2026-01-01_00-00-00/SPIM/derivatives/something"
    mock_s3.get_object.return_value = {"Body": BytesIO(json.dumps({"ng_link": ng_link}).encode())}
    result = _fetch_raw_ng_link(RAW_NAME)
    assert result == ng_link
    mock_s3.get_object.assert_called_once_with(
        Bucket="aind-open-data",
        Key=f"{RAW_NAME}/SPIM/derivatives/neuroglancer_config.json",
    )

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.boto3.client")
def test_fetch_raw_ng_link_fixes_missing_spim_prefix(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    broken_link = "https://allen.neuroglass.io/new#!s3://aind-open-data/SmartSPIM_123_2026-01-01_00-00-00/derivatives/something"
    fixed_link = "https://allen.neuroglass.io/new#!s3://aind-open-data/SmartSPIM_123_2026-01-01_00-00-00/SPIM/derivatives/something"
    mock_s3.get_object.return_value = {"Body": BytesIO(json.dumps({"ng_link": broken_link}).encode())}
    result = _fetch_raw_ng_link(RAW_NAME)
    assert result == fixed_link

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.boto3.client")
def test_fetch_raw_ng_link_returns_none_on_s3_error(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.get_object.side_effect = Exception("NoSuchKey")
    result = _fetch_raw_ng_link(RAW_NAME)
    assert result is None


# --- _fetch_asset_metadata ---

@patch("zombie_squirrel.acorn_helpers.assets_smartspim.MetadataDbClient")
def test_fetch_asset_metadata_returns_dict_keyed_by_name(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [EXAMPLE_RECORD]
    result = _fetch_asset_metadata([STITCHED_NAME])
    assert STITCHED_NAME in result
    assert result[STITCHED_NAME]["_id"] == "abc123"

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
def test_build_rows_one_row_per_channel(mock_list_channels):
    mock_list_channels.return_value = ["Ex_488_Em_525", "Ex_561_Em_600"]
    rows = _build_rows({RAW_NAME: STITCHED_NAME}, {STITCHED_NAME: EXAMPLE_RECORD}, {RAW_NAME: None})
    assert len(rows) == 2
    assert rows[0]["channel"] == "Ex_488_Em_525"
    assert rows[1]["channel"] == "Ex_561_Em_600"

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_processed_row_fields_populated(mock_list_channels):
    mock_list_channels.return_value = ["Ex_561_Em_600"]
    raw_link = "https://example.com/raw_ng_link"
    rows = _build_rows({RAW_NAME: STITCHED_NAME}, {STITCHED_NAME: EXAMPLE_RECORD}, {RAW_NAME: raw_link})
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == STITCHED_NAME
    assert row["raw_name"] == RAW_NAME
    assert row["processing_end_time"] == "2026-01-02T12:00:00"
    assert row["stitched_link"] == _stitched_link(LOCATION)
    assert row["raw_link"] == raw_link
    assert row["channel"] == "Ex_561_Em_600"
    assert row["segmentation_link"] == _segmentation_link(LOCATION, "Ex_561_Em_600")
    assert row["quantification_link"] == _quantification_link(LOCATION, "Ex_561_Em_600")
    assert row["processed"] is True

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_processed_no_channels_emits_single_null_row(mock_list_channels):
    mock_list_channels.return_value = []
    rows = _build_rows({RAW_NAME: STITCHED_NAME}, {STITCHED_NAME: EXAMPLE_RECORD}, {RAW_NAME: None})
    assert len(rows) == 1
    assert rows[0]["channel"] is None
    assert rows[0]["segmentation_link"] is None
    assert rows[0]["quantification_link"] is None
    assert rows[0]["processed"] is True
    assert rows[0]["name"] == STITCHED_NAME
    assert rows[0]["raw_name"] == RAW_NAME

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_unprocessed_row_has_no_links(mock_list_channels):
    raw_link = "https://example.com/raw_ng_link"
    row = _build_rows({RAW_NAME: None}, {}, {RAW_NAME: raw_link})[0]
    assert row["name"] == RAW_NAME
    assert row["raw_name"] == RAW_NAME
    assert row["processing_end_time"] is None
    assert row["stitched_link"] is None
    assert row["raw_link"] == raw_link
    assert row["channel"] is None
    assert row["segmentation_link"] is None
    assert row["quantification_link"] is None
    assert row["processed"] is False
    mock_list_channels.assert_not_called()

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_uses_last_data_process_end_time(mock_list_channels):
    mock_list_channels.return_value = []
    record = {**EXAMPLE_RECORD, "processing": {"data_processes": [
        {"end_date_time": "2026-01-01T10:00:00"}, {"end_date_time": "2026-01-02T12:00:00"}
    ]}}
    rows = _build_rows({RAW_NAME: STITCHED_NAME}, {STITCHED_NAME: record}, {RAW_NAME: None})
    assert rows[0]["processing_end_time"] == "2026-01-02T12:00:00"

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._list_channels")
def test_build_rows_no_data_processes_gives_null_end_time(mock_list_channels):
    mock_list_channels.return_value = []
    record = {**EXAMPLE_RECORD, "processing": {"data_processes": []}}
    rows = _build_rows({RAW_NAME: STITCHED_NAME}, {STITCHED_NAME: record}, {RAW_NAME: None})
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

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_raw_ng_link")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim._build_rows")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_asset_metadata")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.source_data")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.asset_basics")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_force_update_builds_and_caches(mock_tree, mock_asset_basics, mock_source_data, mock_fetch_meta, mock_build_rows, mock_raw_ng_link):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_asset_basics.return_value = pd.DataFrame({"data_level": ["raw"], "modalities": ["SPIM"], "name": [RAW_NAME]})
    mock_source_data.return_value = pd.DataFrame({
        "name": [STITCHED_NAME],
        "source_data": [RAW_NAME],
        "pipeline_name": ["stitching"],
        "processing_time": ["2026-01-02_00-00-00"],
    })
    mock_fetch_meta.return_value = {}
    mock_raw_ng_link.return_value = None
    mock_build_rows.return_value = [{"name": STITCHED_NAME, "raw_name": RAW_NAME, "processed": True, "channel": "Ex_561_Em_600"}]
    result = assets_smartspim(force_update=True)
    assert len(result) == 1
    mock_tree.hide.assert_called_once()

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_raw_ng_link")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.source_data")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.asset_basics")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_unprocessed_assets_included_with_processed_false(mock_tree, mock_asset_basics, mock_source_data, mock_raw_ng_link):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_asset_basics.return_value = pd.DataFrame({"data_level": ["raw"], "modalities": ["SPIM"], "name": [RAW_NAME]})
    mock_source_data.return_value = pd.DataFrame({
        "name": [f"{RAW_NAME}_processed_2026-01-02_00-00-00"],
        "source_data": [RAW_NAME],
        "pipeline_name": ["processing"],
        "processing_time": ["2026-01-02_00-00-00"],
    })
    mock_raw_ng_link.return_value = None
    with patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_asset_metadata", return_value={}):
        with patch("zombie_squirrel.acorn_helpers.assets_smartspim._build_rows", return_value=[{"name": RAW_NAME, "raw_name": RAW_NAME, "processed": False, "channel": None}]) as mock_build:
            assets_smartspim(force_update=True)
    raw_to_stitched_arg = mock_build.call_args[0][0]
    assert RAW_NAME in raw_to_stitched_arg
    assert raw_to_stitched_arg[RAW_NAME] is None
    mock_tree.hide.assert_called_once()

@patch("zombie_squirrel.acorn_helpers.assets_smartspim._fetch_raw_ng_link")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.source_data")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.asset_basics")
@patch("zombie_squirrel.acorn_helpers.assets_smartspim.acorns.TREE")
def test_filters_only_raw_spim_assets(mock_tree, mock_asset_basics, mock_source_data, mock_raw_ng_link):
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
    mock_raw_ng_link.return_value = None
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
        "name", "raw_name", "processed", "processing_end_time",
        "stitched_link", "raw_link", "channel", "segmentation_link", "quantification_link",
    ]
