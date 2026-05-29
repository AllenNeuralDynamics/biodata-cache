"""Unit tests for platform_qc acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import zombie_squirrel.acorns as acorns
from zombie_squirrel.acorn_helpers.platform_qc import platform_qc, PLATFORMS
from zombie_squirrel.forest import MemoryTree


@pytest.fixture(autouse=True)
def memory_tree():
    acorns.TREE = MemoryTree()


@pytest.fixture
def basics_df():
    return pd.DataFrame({
        "name": ["spim_asset_1", "spim_asset_2", "fib_asset_1", "vr_asset_1"],
        "subject_id": ["subj1", "subj1", "subj2", "subj3"],
        "modalities": ["SPIM", "SPIM", "fib", "ecephys"],
        "instrument_id": ["rig_a", "rig_b", None, "rig_c"],
        "experimenters": ["Alice, Bob", "Charlie", None, "Dave"],
        "acquisition_start_time": ["2025-06-01T10:00:00", "2025-06-02T10:00:00", "2025-06-03T10:00:00", "2025-06-04T10:00:00"],
        "acquisition_type": [None, None, None, "AindVrForaging"],
    })


@pytest.fixture
def tag_status_subj1():
    return pd.DataFrame({
        "tag": ["tagA:Suite", "tagB:Suite"],
        "status": ["Pass", "Fail"],
        "asset_name": ["spim_asset_1", "spim_asset_1"],
        "subject_id": ["subj1", "subj1"],
        "timestamp": pd.to_datetime(["2025-06-01", "2025-06-01"]),
    })


@pytest.fixture
def tag_status_subj2():
    return pd.DataFrame({
        "tag": ["tagC:Suite"],
        "status": ["Pass"],
        "asset_name": ["fib_asset_1"],
        "subject_id": ["subj2"],
        "timestamp": pd.to_datetime(["2025-06-03"]),
    })


def test_platforms_list():
    assert "spim" in PLATFORMS
    assert "fib" in PLATFORMS
    assert "vr" in PLATFORMS
    assert "dynamic_foraging" in PLATFORMS


def test_platform_qc_cache_hit(basics_df, tag_status_subj1):
    cached = pd.DataFrame({
        "asset_name": ["spim_asset_1"],
        "subject_id": ["subj1"],
        "instrument_id": ["rig_a"],
        "experimenter": ["Alice"],
        "tag": ["tagA:Suite"],
        "status": ["Pass"],
        "timestamp": pd.to_datetime(["2025-06-01"]),
    })
    acorns.TREE.hide("platform_qc/spim", cached)
    df = platform_qc("spim", force_update=False)
    assert len(df) == 1
    assert df.iloc[0]["tag"] == "tagA:Suite"


def test_platform_qc_empty_cache_raises(basics_df):
    with pytest.raises(ValueError, match="Cache is empty"):
        platform_qc("spim", force_update=False)


def test_platform_qc_spim_builds_from_memory(basics_df, tag_status_subj1):
    acorns.TREE.hide("asset_basics", basics_df)
    acorns.TREE.hide("qc_tag_status/subj1", tag_status_subj1)

    df = platform_qc("spim", force_update=True)

    assert not df.empty
    assert set(df.columns) >= {"asset_name", "subject_id", "instrument_id", "experimenter", "tag", "status"}
    assert set(df["asset_name"].unique()) == {"spim_asset_1"}
    assert set(df["tag"].unique()) == {"tagA:Suite", "tagB:Suite"}


def test_platform_qc_experimenter_exploded(basics_df, tag_status_subj1):
    acorns.TREE.hide("asset_basics", basics_df)
    acorns.TREE.hide("qc_tag_status/subj1", tag_status_subj1)

    df = platform_qc("spim", force_update=True)

    experimenters = df["experimenter"].unique().tolist()
    assert "Alice" in experimenters
    assert "Bob" in experimenters


def test_platform_qc_unknown_instrument(basics_df, tag_status_subj2):
    acorns.TREE.hide("asset_basics", basics_df)
    acorns.TREE.hide("qc_tag_status/subj2", tag_status_subj2)

    df = platform_qc("fib", force_update=True)

    assert df.iloc[0]["instrument_id"] == "(unknown)"
    assert df.iloc[0]["experimenter"] == "(unknown)"


def test_platform_qc_vr(basics_df):
    tag_status = pd.DataFrame({
        "tag": ["tagD:Suite"],
        "status": ["Pass"],
        "asset_name": ["vr_asset_1"],
        "subject_id": ["subj3"],
        "timestamp": pd.to_datetime(["2025-06-04"]),
    })
    acorns.TREE.hide("asset_basics", basics_df)
    acorns.TREE.hide("qc_tag_status/subj3", tag_status)

    df = platform_qc("vr", force_update=True)

    assert len(df) == 1
    assert df.iloc[0]["tag"] == "tagD:Suite"
    assert df.iloc[0]["experimenter"] == "Dave"


def test_platform_qc_no_qc_data_returns_empty(basics_df):
    acorns.TREE.hide("asset_basics", basics_df)
    df = platform_qc("spim", force_update=True)
    assert df.empty


def test_platform_qc_result_cached(basics_df, tag_status_subj1):
    acorns.TREE.hide("asset_basics", basics_df)
    acorns.TREE.hide("qc_tag_status/subj1", tag_status_subj1)

    platform_qc("spim", force_update=True)

    cached = acorns.TREE.scurry("platform_qc/spim")
    assert not cached.empty

