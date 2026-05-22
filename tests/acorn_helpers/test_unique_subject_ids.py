"""Unit tests for unique_subject_ids acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.unique_subject_ids import unique_subject_ids


@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.acorns.TREE")
def test_cache_hit(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame({"subject_id": ["sub001", "sub002"]})
    result = unique_subject_ids(force_update=False)
    assert result == ["sub001", "sub002"]
    mock_client_class.assert_not_called()


@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.acorns.TREE")
def test_empty_cache_raises_error(mock_tree):
    mock_tree.scurry.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        unique_subject_ids(force_update=False)


@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.acorns.TREE")
def test_cache_miss(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [{"subject_id": "sub001"}, {"subject_id": "sub002"}]
    result = unique_subject_ids(force_update=True)
    assert result == ["sub001", "sub002"]
    mock_client_class.assert_called_once()


@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_subject_ids.acorns.TREE")
def test_force_update(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame({"subject_id": ["old_sub"]})
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [{"subject_id": "new_sub"}]
    result = unique_subject_ids(force_update=True)
    assert result == ["new_sub"]
