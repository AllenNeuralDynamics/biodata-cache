"""Unit tests for zombie_squirrel.trees module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from zombie_squirrel.forest import MemoryTree, S3Tree, Tree
from zombie_squirrel.utils import ZS_VERSION

_VF = f"zs-v{ZS_VERSION}"


# --- Tree abstract class ---

def test_tree_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Tree()

def test_tree_subclass_must_implement_hide():
    class IncompleteTree(Tree):
        def scurry(self, table_name: str) -> pd.DataFrame:  # pragma: no cover
            return pd.DataFrame()
    with pytest.raises(TypeError):
        IncompleteTree()

def test_tree_subclass_must_implement_scurry():
    class IncompleteTree(Tree):
        def hide(self, table_name: str, data: pd.DataFrame) -> None:  # pragma: no cover
            pass
    with pytest.raises(TypeError):
        IncompleteTree()


# --- MemoryTree ---

@pytest.fixture
def tree():
    return MemoryTree()

def test_hide_and_scurry_basic(tree):
    df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
    tree.hide("test_table", df)
    pd.testing.assert_frame_equal(df, tree.scurry("test_table"))

def test_scurry_empty_table(tree):
    result = tree.scurry("nonexistent_table")
    assert result.empty
    assert isinstance(result, pd.DataFrame)

def test_hide_overwrites_existing(tree):
    tree.hide("table", pd.DataFrame({"col1": [1, 2, 3]}))
    df2 = pd.DataFrame({"col1": [4, 5, 6]})
    tree.hide("table", df2)
    pd.testing.assert_frame_equal(df2, tree.scurry("table"))

def test_multiple_tables(tree):
    df1 = pd.DataFrame({"col1": [1, 2]})
    df2 = pd.DataFrame({"col2": ["a", "b"]})
    tree.hide("table1", df1)
    tree.hide("table2", df2)
    pd.testing.assert_frame_equal(df1, tree.scurry("table1"))
    pd.testing.assert_frame_equal(df2, tree.scurry("table2"))

def test_hide_empty_dataframe(tree):
    df = pd.DataFrame()
    tree.hide("empty_table", df)
    pd.testing.assert_frame_equal(df, tree.scurry("empty_table"))

def test_scurry_multiple_tables(tree):
    df1 = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
    df2 = pd.DataFrame({"col1": [3, 4], "col2": ["c", "d"]})
    tree.hide("table1", df1)
    tree.hide("table2", df2)
    result = tree.scurry(["table1", "table2"])
    assert len(result) == 4
    assert "asset_name" in result.columns
    assert result[result["col1"] == 1].iloc[0]["asset_name"] == "table1"
    assert result[result["col1"] == 3].iloc[0]["asset_name"] == "table2"

def test_scurry_multiple_with_missing_table(tree):
    tree.hide("table1", pd.DataFrame({"col1": [1, 2]}))
    result = tree.scurry(["table1", "nonexistent"])
    assert len(result) == 2
    assert "asset_name" in result.columns
    assert (result["asset_name"] == "table1").all()

def test_scurry_multiple_all_missing(tree):
    result = tree.scurry(["missing1", "missing2"])
    assert result.empty
    assert isinstance(result, pd.DataFrame)


# --- S3Tree ---

@patch("zombie_squirrel.forest.boto3.client")
def test_s3_acorn_initialization(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    acorn = S3Tree()
    assert acorn.bucket == "allen-data-views"
    assert acorn.s3_client == mock_s3_client
    mock_boto3_client.assert_called_once_with("s3")

@patch("zombie_squirrel.forest.boto3.client")
def test_s3_hide(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    acorn = S3Tree()
    acorn.hide("test_table", pd.DataFrame({"col1": [1, 2, 3]}))
    assert mock_s3_client.put_object.call_count == 2
    parquet_call = mock_s3_client.put_object.call_args_list[0][1]
    assert parquet_call["Bucket"] == "allen-data-views"
    assert parquet_call["Key"] == f"data-asset-cache/{_VF}/test_table.pqt"
    assert isinstance(parquet_call["Body"], bytes)
    json_call = mock_s3_client.put_object.call_args_list[1][1]
    assert json_call["Bucket"] == "allen-data-views"
    assert json_call["Key"] == f"data-asset-cache/{_VF}/test_table.json"
    assert "columns" in json_call["Body"]

@patch("zombie_squirrel.forest.boto3.client")
def test_s3_hide_qc_metadata(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    acorn = S3Tree()
    acorn.hide("qc/subject123", pd.DataFrame({"metric": ["value1", "value2"]}))
    assert mock_s3_client.put_object.call_count == 2
    parquet_call = mock_s3_client.put_object.call_args_list[0][1]
    assert parquet_call["Key"] == f"data-asset-cache/{_VF}/qc/subject_id=subject123/data.pqt"
    json_call = mock_s3_client.put_object.call_args_list[1][1]
    assert json_call["Bucket"] == "allen-data-views"
    assert json_call["Key"] == f"data-asset-cache/{_VF}/qc.json"
    assert "columns" in json_call["Body"]
    assert "metric" in json_call["Body"]

@patch("zombie_squirrel.forest.boto3.client")
def test_s3_hide_platform_qc_metadata(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    acorn = S3Tree()
    acorn.hide("platform_qc/spim", pd.DataFrame({"tag": ["a"]}))
    parquet_call = mock_s3_client.put_object.call_args_list[0][1]
    assert parquet_call["Key"] == f"data-asset-cache/{_VF}/platform_qc/platform=spim/data.pqt"
    json_call = mock_s3_client.put_object.call_args_list[1][1]
    assert json_call["Key"] == f"data-asset-cache/{_VF}/platform_qc.json"

@patch("zombie_squirrel.forest.duckdb.query")
@patch("zombie_squirrel.forest.boto3.client")
def test_s3_scurry(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    expected_df = pd.DataFrame({"col1": [1, 2, 3]})
    mock_result = MagicMock()
    mock_result.to_df.return_value = expected_df
    mock_duckdb_query.return_value = mock_result
    acorn = S3Tree()
    result = acorn.scurry("test_table")
    mock_duckdb_query.assert_called_once()
    assert f"data-asset-cache/{_VF}/test_table.pqt" in mock_duckdb_query.call_args[0][0]
    pd.testing.assert_frame_equal(result, expected_df)

@patch("zombie_squirrel.forest.duckdb.query")
@patch("zombie_squirrel.forest.boto3.client")
def test_s3_scurry_partitioned_table(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    expected_df = pd.DataFrame({"metric": ["a"]})
    mock_result = MagicMock()
    mock_result.to_df.return_value = expected_df
    mock_duckdb_query.return_value = mock_result
    result = S3Tree().scurry("qc/subject123")
    assert f"data-asset-cache/{_VF}/qc/subject_id=subject123/data.pqt" in mock_duckdb_query.call_args[0][0]
    pd.testing.assert_frame_equal(result, expected_df)

@patch("zombie_squirrel.forest.boto3.client")
def test_s3_get_location_single_partition(mock_boto3_client):
    mock_boto3_client.return_value = MagicMock()
    tree = S3Tree()
    result = tree.get_location("qc/subject123")
    assert result == f"s3://allen-data-views/data-asset-cache/{_VF}/qc/subject_id=subject123/data.pqt"

@patch("zombie_squirrel.forest.boto3.client")
def test_s3_get_location_platform_qc_partition(mock_boto3_client):
    mock_boto3_client.return_value = MagicMock()
    tree = S3Tree()
    result = tree.get_location("platform_qc/spim")
    assert result == f"s3://allen-data-views/data-asset-cache/{_VF}/platform_qc/platform=spim/data.pqt"

@patch("zombie_squirrel.forest.duckdb.query")
@patch("zombie_squirrel.forest.boto3.client")
def test_s3_scurry_handles_error(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    mock_duckdb_query.side_effect = Exception("S3 access error")
    result = S3Tree().scurry("nonexistent_table")
    assert result.empty
    assert isinstance(result, pd.DataFrame)

@patch("zombie_squirrel.forest.duckdb.query")
@patch("zombie_squirrel.forest.boto3.client")
def test_s3_scurry_multiple_tables(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    expected_df = pd.DataFrame(
        {"col1": [1, 2, 3, 4], "col2": ["a", "b", "c", "d"], "asset_name": ["table1", "table1", "table2", "table2"]}
    )
    mock_result = MagicMock()
    mock_result.to_df.return_value = expected_df
    mock_duckdb_query.return_value = mock_result
    result = S3Tree().scurry(["table1", "table2"])
    mock_duckdb_query.assert_called_once()
    query_call = mock_duckdb_query.call_args[0][0]
    assert "UNION ALL" in query_call
    assert "'table1' as asset_name" in query_call
    assert "'table2' as asset_name" in query_call
    pd.testing.assert_frame_equal(result, expected_df)

@patch("zombie_squirrel.forest.duckdb.query")
@patch("zombie_squirrel.forest.boto3.client")
def test_s3_scurry_multiple_handles_error(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    mock_duckdb_query.side_effect = Exception("Merge error")
    result = S3Tree().scurry(["table1", "table2"])
    assert result.empty
    assert isinstance(result, pd.DataFrame)
