"""Unit tests for raw_to_derived helper."""

from unittest.mock import patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.raw_to_derived import raw_to_derived


def _make_df(rows):
    return pd.DataFrame(rows, columns=["name", "source_data", "pipeline_name", "processing_time"])


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_returns_matching_derived_names(mock_source_data):
    mock_source_data.return_value = _make_df([
        ("derived_a_2026-01-02_00-00-00", "raw_x", "pipeline_a", "2026-01-02_00-00-00"),
        ("derived_b_2026-01-03_00-00-00", "raw_x", "pipeline_b", "2026-01-03_00-00-00"),
        ("derived_c_2026-01-01_00-00-00", "raw_y", "pipeline_a", "2026-01-01_00-00-00"),
    ])
    result = raw_to_derived("raw_x")
    assert sorted(result) == sorted(["derived_a_2026-01-02_00-00-00", "derived_b_2026-01-03_00-00-00"])


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_returns_empty_set_no_match(mock_source_data):
    mock_source_data.return_value = _make_df([("derived_a_2026-01-01_00-00-00", "raw_y", "pipeline_a", "2026-01-01_00-00-00")])
    assert raw_to_derived("raw_x") == []


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_latest_returns_most_recent_per_pipeline(mock_source_data):
    mock_source_data.return_value = _make_df([
        ("derived_old_2026-01-01_00-00-00", "raw_x", "pipeline_a", "2026-01-01_00-00-00"),
        ("derived_new_2026-01-03_00-00-00", "raw_x", "pipeline_a", "2026-01-03_00-00-00"),
        ("derived_b_2026-01-02_00-00-00", "raw_x", "pipeline_b", "2026-01-02_00-00-00"),
    ])
    result = raw_to_derived("raw_x", latest=True)
    assert sorted(result) == sorted(["derived_new_2026-01-03_00-00-00", "derived_b_2026-01-02_00-00-00"])
    assert "derived_old_2026-01-01_00-00-00" not in result


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_latest_false_returns_all(mock_source_data):
    mock_source_data.return_value = _make_df([
        ("derived_old_2026-01-01_00-00-00", "raw_x", "pipeline_a", "2026-01-01_00-00-00"),
        ("derived_new_2026-01-03_00-00-00", "raw_x", "pipeline_a", "2026-01-03_00-00-00"),
    ])
    result = raw_to_derived("raw_x", latest=False)
    assert sorted(result) == sorted(["derived_old_2026-01-01_00-00-00", "derived_new_2026-01-03_00-00-00"])


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_latest_empty_matches(mock_source_data):
    mock_source_data.return_value = _make_df([("derived_a_2026-01-01_00-00-00", "raw_y", "pipeline_a", "2026-01-01_00-00-00")])
    assert raw_to_derived("raw_x", latest=True) == []


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.asset_basics")
@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_modality_filters_by_modality(mock_source_data, mock_asset_basics):
    mock_source_data.return_value = _make_df([
        ("derived_ecephys_2026-01-01_00-00-00", "raw_x", "pipeline_a", "2026-01-01_00-00-00"),
        ("derived_behavior_2026-01-01_00-00-00", "raw_x", "pipeline_b", "2026-01-01_00-00-00"),
    ])
    mock_asset_basics.return_value = pd.DataFrame([
        {"name": "derived_ecephys_2026-01-01_00-00-00", "modalities": ["ecephys"]},
        {"name": "derived_behavior_2026-01-01_00-00-00", "modalities": ["behavior"]},
    ])
    assert raw_to_derived("raw_x", modality="ecephys") == ["derived_ecephys_2026-01-01_00-00-00"]


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.asset_basics")
@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_modality_latest_returns_most_recent_for_modality(mock_source_data, mock_asset_basics):
    mock_source_data.return_value = _make_df([
        ("derived_ecephys_old_2026-01-01_00-00-00", "raw_x", "pipeline_a", "2026-01-01_00-00-00"),
        ("derived_ecephys_new_2026-01-03_00-00-00", "raw_x", "pipeline_a", "2026-01-03_00-00-00"),
        ("derived_behavior_2026-01-04_00-00-00", "raw_x", "pipeline_a", "2026-01-04_00-00-00"),
    ])
    mock_asset_basics.return_value = pd.DataFrame([
        {"name": "derived_ecephys_old_2026-01-01_00-00-00", "modalities": ["ecephys"]},
        {"name": "derived_ecephys_new_2026-01-03_00-00-00", "modalities": ["ecephys"]},
        {"name": "derived_behavior_2026-01-04_00-00-00", "modalities": ["behavior"]},
    ])
    result = raw_to_derived("raw_x", latest=True, modality="ecephys")
    assert result == ["derived_ecephys_new_2026-01-03_00-00-00"]
    assert "derived_ecephys_old_2026-01-01_00-00-00" not in result
    assert "derived_behavior_2026-01-04_00-00-00" not in result


@patch("zombie_squirrel.acorn_helpers.raw_to_derived.asset_basics")
@patch("zombie_squirrel.acorn_helpers.raw_to_derived.source_data")
def test_modality_no_match_returns_empty(mock_source_data, mock_asset_basics):
    mock_source_data.return_value = _make_df([("derived_behavior_2026-01-01_00-00-00", "raw_x", "pipeline_a", "2026-01-01_00-00-00")])
    mock_asset_basics.return_value = pd.DataFrame([{"name": "derived_behavior_2026-01-01_00-00-00", "modalities": ["behavior"]}])
    assert raw_to_derived("raw_x", modality="ecephys") == []
