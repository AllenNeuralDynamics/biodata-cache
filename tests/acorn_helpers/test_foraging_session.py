"""Unit tests for the foraging session acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.foraging.session import (
    _TABLE_NAME,
    _add_asset_name,
    foraging_session,
    foraging_session_columns,
)


def _make_session_df(**overrides):
    row = {
        "subject_id": "123456",
        "session_date": "2024-01-15",
        "nwb_suffix": 100000,
        "_session_id": "123456_2024-01-15_100000",
        "co_s3_nwb_uri": "s3://bucket/asset-id/nwb/behavior_123456_2024-01-15_10-00-00.nwb",
        "foraging_eff": 0.75,
        "finished_trials": 300.0,
    }
    row.update(overrides)
    return pd.DataFrame([row])


class TestAddAssetName:
    def test_extracts_from_valid_uri(self):
        df = _make_session_df()
        result = _add_asset_name(df)
        assert result["asset_name"].iloc[0] == "behavior_123456_2024-01-15_10-00-00"

    def test_nan_when_uri_is_nan(self):
        df = _make_session_df(co_s3_nwb_uri=float("nan"))
        result = _add_asset_name(df)
        assert pd.isna(result["asset_name"].iloc[0])

    def test_does_not_mutate_input(self):
        df = _make_session_df()
        original_cols = set(df.columns)
        _add_asset_name(df)
        assert set(df.columns) == original_cols

    def test_multiple_rows(self):
        df = pd.DataFrame([
            {"co_s3_nwb_uri": "s3://b/a1/nwb/behavior_111_2024-01-01_09-00-00.nwb"},
            {"co_s3_nwb_uri": "s3://b/a2/nwb/behavior_222_2024-02-01_10-30-00.nwb"},
            {"co_s3_nwb_uri": float("nan")},
        ])
        result = _add_asset_name(df)
        assert result["asset_name"].iloc[0] == "behavior_111_2024-01-01_09-00-00"
        assert result["asset_name"].iloc[1] == "behavior_222_2024-02-01_10-30-00"
        assert pd.isna(result["asset_name"].iloc[2])


class TestForagingSessionAcorn:
    @patch("zombie_squirrel.acorn_helpers.foraging.session.acorns.TREE")
    def test_cache_hit_returns_df(self, mock_tree):
        cached = _make_session_df()
        mock_tree.scurry.return_value = cached
        result = foraging_session(force_update=False)
        mock_tree.scurry.assert_called_once_with(_TABLE_NAME)
        assert len(result) == 1

    @patch("zombie_squirrel.acorn_helpers.foraging.session.acorns.TREE")
    def test_empty_cache_raises(self, mock_tree):
        mock_tree.scurry.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="Cache is empty"):
            foraging_session(force_update=False)

    @patch("zombie_squirrel.acorn_helpers.foraging.session._fetch_upstream")
    @patch("zombie_squirrel.acorn_helpers.foraging.session.acorns.TREE")
    def test_force_update_fetches_and_hides(self, mock_tree, mock_fetch):
        mock_tree.scurry.return_value = pd.DataFrame()
        fresh = _make_session_df()
        mock_fetch.return_value = fresh
        result = foraging_session(force_update=True)
        mock_fetch.assert_called_once()
        mock_tree.hide.assert_called_once_with(_TABLE_NAME, fresh)
        assert len(result) == 1

    @patch("zombie_squirrel.acorn_helpers.foraging.session._fetch_upstream")
    @patch("zombie_squirrel.acorn_helpers.foraging.session.acorns.TREE")
    def test_cold_cache_with_force_update_fetches(self, mock_tree, mock_fetch):
        mock_tree.scurry.return_value = _make_session_df()
        fresh = _make_session_df(foraging_eff=0.9)
        mock_fetch.return_value = fresh
        result = foraging_session(force_update=True)
        mock_fetch.assert_called_once()
        assert result["foraging_eff"].iloc[0] == 0.9

    @patch("zombie_squirrel.acorn_helpers.foraging.session._fetch_upstream")
    @patch("zombie_squirrel.acorn_helpers.foraging.session.acorns.TREE")
    def test_no_fetch_on_warm_cache(self, mock_tree, mock_fetch):
        mock_tree.scurry.return_value = _make_session_df()
        foraging_session(force_update=False)
        mock_fetch.assert_not_called()


class TestForagingSessionColumns:
    def test_returns_list_of_columns(self):
        cols = foraging_session_columns()
        assert isinstance(cols, list)
        assert len(cols) > 0

    def test_has_asset_name_column(self):
        names = [c.name for c in foraging_session_columns()]
        assert "asset_name" in names

    def test_has_session_id_column(self):
        names = [c.name for c in foraging_session_columns()]
        assert "_session_id" in names

    def test_all_columns_have_descriptions(self):
        for col in foraging_session_columns():
            assert col.description, f"Column '{col.name}' has no description"
