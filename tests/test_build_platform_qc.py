"""Unit tests for platform_qc acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import zombie_squirrel.acorns as acorns
from zombie_squirrel.acorn_helpers.platform_qc import (
    PLATFORMS,
    _filter_tags_by_modality,
    platform_qc,
)
from zombie_squirrel.forest import MemoryTree


@pytest.fixture(autouse=True)
def memory_tree():
    acorns.TREE = MemoryTree()


@pytest.fixture
def basics_df():
    return pd.DataFrame({
        "name": ["spim_asset_1", "spim_asset_2", "fib_asset_1", "behavior_asset_1"],
        "subject_id": ["subj1", "subj1", "subj2", "subj3"],
        "modalities": ["SPIM", "SPIM", "fib", "behavior, behavior-videos"],
        "instrument_id": ["rig_a", "rig_b", None, "rig_c"],
        "experimenters": ["Alice, Bob", "Charlie", None, "Dave"],
        "acquisition_start_time": ["2025-06-01T10:00:00", "2025-06-02T10:00:00", "2025-06-03T10:00:00", "2025-06-04T10:00:00"],
        "acquisition_type": [None, None, None, "Uncoupled Baiting"],
    })


MOCK_SPIM_RECORD = {
    "name": "spim_asset_1",
    "subject": {"subject_id": "subj1"},
    "quality_control": {
        "metrics": [
            {"name": "metric_a", "modality": {"abbreviation": "SPIM"}, "tags": {"type": "Alignment"}},
            {"name": "metric_b", "modality": {"abbreviation": "SPIM"}, "tags": {"type": "Resolution"}},
        ],
        "status": {"type:Alignment": "Pass", "type:Resolution": "Fail", "SPIM": "Fail"},
    },
}

MOCK_BEHAVIOR_RECORD = {
    "name": "behavior_asset_1",
    "subject": {"subject_id": "subj3"},
    "quality_control": {
        "metrics": [
            {"name": "dropped frames", "modality": {"abbreviation": "behavior-videos"}, "tags": {"type": "dropped frames check"}},
            {"name": "side bias", "modality": {"abbreviation": "behavior"}, "tags": {"type": "Side bias"}},
            {"name": "lick intervals", "modality": {"abbreviation": "behavior"}, "tags": {"type": "Lick Intervals"}},
            {"name": "fib signal", "modality": {"abbreviation": "fib"}, "tags": {"type": "CMOS Floor signal"}},
        ],
        "status": {
            "type:dropped frames check": "Pass",
            "type:Side bias": "Pass",
            "type:Lick Intervals": "Pass",
            "type:CMOS Floor signal": "Fail",
            "behavior": "Pass",
            "behavior-videos": "Pass",
            "fib": "Fail",
        },
    },
}


def test_platforms_list():
    assert "spim" in PLATFORMS
    assert "fib" in PLATFORMS
    assert "vr" in PLATFORMS
    assert "dynamic_foraging" in PLATFORMS


def test_filter_tags_by_modality_behavior():
    qc = MOCK_BEHAVIOR_RECORD["quality_control"]
    result = _filter_tags_by_modality(qc, {"behavior", "behavior-videos"})
    tag_keys = [t[0] for t in result]
    assert "type:Side bias" in tag_keys
    assert "type:Lick Intervals" in tag_keys
    assert "type:dropped frames check" in tag_keys
    assert "behavior" in tag_keys
    assert "behavior-videos" in tag_keys
    assert "type:CMOS Floor signal" not in tag_keys
    assert "fib" not in tag_keys


def test_filter_tags_by_modality_spim():
    qc = MOCK_SPIM_RECORD["quality_control"]
    result = _filter_tags_by_modality(qc, {"SPIM"})
    tag_keys = [t[0] for t in result]
    assert "type:Alignment" in tag_keys
    assert "type:Resolution" in tag_keys
    assert "SPIM" in tag_keys


def test_platform_qc_cache_hit():
    cached = pd.DataFrame({
        "asset_name": ["spim_asset_1"],
        "tag": ["type:Alignment"],
        "status": ["Pass"],
        "timestamp": pd.to_datetime(["2025-06-01"]),
    })
    acorns.TREE.hide("platform_qc/spim", cached)
    df = platform_qc("spim", force_update=False)
    assert len(df) == 1
    assert df.iloc[0]["tag"] == "type:Alignment"


def test_platform_qc_empty_cache_raises():
    with pytest.raises(ValueError, match="Cache is empty"):
        platform_qc("spim", force_update=False)


@patch("zombie_squirrel.acorn_helpers.platform_qc.MetadataDbClient")
def test_platform_qc_spim_builds(mock_client_class, basics_df):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [MOCK_SPIM_RECORD]

    acorns.TREE.hide("asset_basics", basics_df)
    df = platform_qc("spim", force_update=True)

    assert not df.empty
    assert set(df["tag"].unique()) == {"type:Alignment", "type:Resolution", "SPIM"}
    assert set(df["asset_name"].unique()) == {"spim_asset_1"}


@patch("zombie_squirrel.acorn_helpers.platform_qc.MetadataDbClient")
def test_platform_qc_dynamic_foraging_filters_modality(mock_client_class, basics_df):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [MOCK_BEHAVIOR_RECORD]

    acorns.TREE.hide("asset_basics", basics_df)
    df = platform_qc("dynamic_foraging", force_update=True)

    assert not df.empty
    tags = set(df["tag"].unique())
    assert "type:Side bias" in tags
    assert "type:Lick Intervals" in tags
    assert "type:dropped frames check" in tags
    assert "behavior" in tags
    assert "behavior-videos" in tags
    assert "type:CMOS Floor signal" not in tags
    assert "fib" not in tags


@patch("zombie_squirrel.acorn_helpers.platform_qc.MetadataDbClient")
def test_platform_qc_no_qc_data_returns_empty(mock_client_class, basics_df):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = []

    acorns.TREE.hide("asset_basics", basics_df)
    df = platform_qc("spim", force_update=True)
    assert df.empty


@patch("zombie_squirrel.acorn_helpers.platform_qc.MetadataDbClient")
def test_platform_qc_result_cached(mock_client_class, basics_df):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [MOCK_SPIM_RECORD]

    acorns.TREE.hide("asset_basics", basics_df)
    platform_qc("spim", force_update=True)

    cached = acorns.TREE.scurry("platform_qc/spim")
    assert not cached.empty

