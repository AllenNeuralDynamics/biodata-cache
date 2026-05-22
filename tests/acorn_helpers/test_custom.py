"""Unit tests for custom acorn."""

from unittest.mock import patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.custom import custom


@patch("zombie_squirrel.acorn_helpers.custom.acorns.TREE")
def test_df_provided_stores_and_returns_df(mock_tree):
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    result = custom(name="my_acorn", df=df)
    mock_tree.hide.assert_called_once_with("my_acorn", df)
    pd.testing.assert_frame_equal(result, df)


@patch("zombie_squirrel.acorn_helpers.custom.acorns.TREE")
def test_retrieval_returns_cached_df(mock_tree):
    cached_df = pd.DataFrame({"x": [10, 20]})
    mock_tree.scurry.return_value = cached_df
    result = custom(name="my_acorn")
    mock_tree.scurry.assert_called_once_with("my_acorn")
    pd.testing.assert_frame_equal(result, cached_df)


@patch("zombie_squirrel.acorn_helpers.custom.acorns.TREE")
def test_retrieval_empty_cache_raises(mock_tree):
    mock_tree.scurry.return_value = pd.DataFrame()
    with pytest.raises(ValueError):
        custom(name="my_acorn")


@patch("zombie_squirrel.acorn_helpers.custom.acorns.TREE")
def test_different_names_are_independent(mock_tree):
    df1 = pd.DataFrame({"a": [1]})
    df2 = pd.DataFrame({"b": [2]})
    mock_tree.scurry.side_effect = lambda name: df1 if name == "acorn_a" else df2
    pd.testing.assert_frame_equal(custom(name="acorn_a"), df1)
    pd.testing.assert_frame_equal(custom(name="acorn_b"), df2)
