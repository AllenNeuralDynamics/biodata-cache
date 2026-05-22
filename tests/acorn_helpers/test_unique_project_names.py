"""Unit tests for unique_project_names acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.unique_project_names import unique_project_names


@patch("zombie_squirrel.acorn_helpers.unique_project_names.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_project_names.acorns.TREE")
def test_cache_hit(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame({"project_name": ["proj1", "proj2", "proj3"]})
    result = unique_project_names(force_update=False)
    assert result == ["proj1", "proj2", "proj3"]
    mock_client_class.assert_not_called()


@patch("zombie_squirrel.acorn_helpers.unique_project_names.acorns.TREE")
def test_empty_cache_raises_error(mock_tree):
    mock_tree.scurry.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        unique_project_names(force_update=False)


@patch("zombie_squirrel.acorn_helpers.unique_project_names.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_project_names.acorns.TREE")
def test_cache_miss(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [{"project_name": "proj1"}, {"project_name": "proj2"}]
    result = unique_project_names(force_update=True)
    assert result == ["proj1", "proj2"]
    mock_client_class.assert_called_once()
    mock_client_instance.aggregate_docdb_records.assert_called_once()


@patch("zombie_squirrel.acorn_helpers.unique_project_names.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_project_names.acorns.TREE")
def test_filters_nan(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame()
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [
        {"project_name": "proj1"}, {"project_name": None}, {"project_name": "proj2"}
    ]
    result = unique_project_names(force_update=True)
    assert result == ["proj1", "proj2"]


@patch("zombie_squirrel.acorn_helpers.unique_project_names.MetadataDbClient")
@patch("zombie_squirrel.acorn_helpers.unique_project_names.acorns.TREE")
def test_force_update(mock_tree, mock_client_class):
    mock_tree.scurry.return_value = pd.DataFrame({"project_name": ["old_proj"]})
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.aggregate_docdb_records.return_value = [{"project_name": "new_proj"}]
    result = unique_project_names(force_update=True)
    assert result == ["new_proj"]
    mock_client_instance.aggregate_docdb_records.assert_called_once()
