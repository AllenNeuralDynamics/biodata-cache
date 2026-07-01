"""Unit tests for biodata_cache.trees module."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from botocore.exceptions import ClientError

from biodata_cache.backend import Backend, MemoryBackend, S3Backend
from biodata_cache.utils import BDC_VERSION

_VF = f"bdc-v{BDC_VERSION}"


def _not_found_error() -> ClientError:
    """Build a 404 ClientError as boto3 head_object raises for a missing key."""
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")



# --- Backend abstract class ---


def test_tree_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Backend()


def test_tree_subclass_must_implement_hide():
    class IncompleteBackend(Backend):
        def read(self, table_name: str) -> pd.DataFrame:  # pragma: no cover
            return pd.DataFrame()

    with pytest.raises(TypeError):
        IncompleteBackend()


def test_tree_subclass_must_implement_scurry():
    class IncompleteBackend(Backend):
        def hide(self, table_name: str, data: pd.DataFrame) -> None:  # pragma: no cover
            pass

    with pytest.raises(TypeError):
        IncompleteBackend()


# --- MemoryBackend ---


@pytest.fixture
def tree():
    return MemoryBackend()


def test_hide_and_scurry_basic(tree):
    df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
    tree.write("test_table", df)
    pd.testing.assert_frame_equal(df, tree.read("test_table"))


def test_scurry_empty_table(tree):
    result = tree.read("nonexistent_table")
    assert result.empty
    assert isinstance(result, pd.DataFrame)


def test_hide_overwrites_existing(tree):
    tree.write("table", pd.DataFrame({"col1": [1, 2, 3]}))
    df2 = pd.DataFrame({"col1": [4, 5, 6]})
    tree.write("table", df2)
    pd.testing.assert_frame_equal(df2, tree.read("table"))


def test_multiple_tables(tree):
    df1 = pd.DataFrame({"col1": [1, 2]})
    df2 = pd.DataFrame({"col2": ["a", "b"]})
    tree.write("table1", df1)
    tree.write("table2", df2)
    pd.testing.assert_frame_equal(df1, tree.read("table1"))
    pd.testing.assert_frame_equal(df2, tree.read("table2"))


def test_hide_empty_dataframe(tree):
    df = pd.DataFrame()
    tree.write("empty_table", df)
    pd.testing.assert_frame_equal(df, tree.read("empty_table"))


def test_scurry_multiple_tables(tree):
    df1 = pd.DataFrame({"col1": [1, 2], "col2": ["a", "b"]})
    df2 = pd.DataFrame({"col1": [3, 4], "col2": ["c", "d"]})
    tree.write("table1", df1)
    tree.write("table2", df2)
    result = tree.read(["table1", "table2"])
    assert len(result) == 4
    assert "asset_name" in result.columns
    assert result[result["col1"] == 1].iloc[0]["asset_name"] == "table1"
    assert result[result["col1"] == 3].iloc[0]["asset_name"] == "table2"


def test_scurry_multiple_with_missing_table(tree):
    tree.write("table1", pd.DataFrame({"col1": [1, 2]}))
    result = tree.read(["table1", "nonexistent"])
    assert len(result) == 2
    assert "asset_name" in result.columns
    assert (result["asset_name"] == "table1").all()


def test_scurry_multiple_all_missing(tree):
    result = tree.read(["missing1", "missing2"])
    assert result.empty
    assert isinstance(result, pd.DataFrame)


# --- S3Backend ---


@patch("biodata_cache.backend.boto3.client")
def test_s3_backend_initialization(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    backend = S3Backend()
    assert backend.bucket == "allen-data-views"
    assert backend.s3_client == mock_s3_client
    mock_boto3_client.assert_called_once_with("s3")


@patch("biodata_cache.backend.boto3.client")
def test_s3_hide(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    backend = S3Backend()
    backend.write("test_table", pd.DataFrame({"col1": [1, 2, 3]}))
    assert mock_s3_client.put_object.call_count == 2
    parquet_call = mock_s3_client.put_object.call_args_list[0][1]
    assert parquet_call["Bucket"] == "allen-data-views"
    assert parquet_call["Key"] == f"data-asset-cache/{_VF}/test_table.pqt"
    assert isinstance(parquet_call["Body"], bytes)
    json_call = mock_s3_client.put_object.call_args_list[1][1]
    assert json_call["Bucket"] == "allen-data-views"
    assert json_call["Key"] == f"data-asset-cache/{_VF}/test_table.json"
    assert "columns" in json_call["Body"]


@patch("biodata_cache.backend.boto3.client")
def test_s3_hide_qc_metadata(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    backend = S3Backend()
    backend.write("qc/subject123", pd.DataFrame({"metric": ["value1", "value2"]}))
    assert mock_s3_client.put_object.call_count == 2
    parquet_call = mock_s3_client.put_object.call_args_list[0][1]
    assert parquet_call["Key"] == f"data-asset-cache/{_VF}/qc/subject_id=subject123/data.pqt"
    json_call = mock_s3_client.put_object.call_args_list[1][1]
    assert json_call["Bucket"] == "allen-data-views"
    assert json_call["Key"] == f"data-asset-cache/{_VF}/qc.json"
    assert "columns" in json_call["Body"]
    assert "metric" in json_call["Body"]


@patch("biodata_cache.backend.boto3.client")
def test_s3_hide_platform_qc_metadata(mock_boto3_client):
    mock_s3_client = MagicMock()
    mock_boto3_client.return_value = mock_s3_client
    backend = S3Backend()
    backend.write("platform_qc/spim", pd.DataFrame({"tag": ["a"]}))
    parquet_call = mock_s3_client.put_object.call_args_list[0][1]
    assert parquet_call["Key"] == f"data-asset-cache/{_VF}/platform_qc/platform=spim/data.pqt"
    json_call = mock_s3_client.put_object.call_args_list[1][1]
    assert json_call["Key"] == f"data-asset-cache/{_VF}/platform_qc.json"


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    expected_df = pd.DataFrame({"col1": [1, 2, 3]})
    mock_duckdb_query.return_value = expected_df
    backend = S3Backend()
    result = backend.read("test_table")
    mock_duckdb_query.assert_called_once()
    assert f"data-asset-cache/{_VF}/test_table.pqt" in mock_duckdb_query.call_args[0][0]
    pd.testing.assert_frame_equal(result, expected_df)


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_partitioned_table(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    expected_df = pd.DataFrame({"metric": ["a"]})
    mock_duckdb_query.return_value = expected_df
    result = S3Backend().read("qc/subject123")
    assert f"data-asset-cache/{_VF}/qc/subject_id=subject123/data*.pqt" in mock_duckdb_query.call_args[0][0]
    pd.testing.assert_frame_equal(result, expected_df)


@patch("biodata_cache.backend.boto3.client")
def test_s3_get_location_single_partition(mock_boto3_client):
    mock_boto3_client.return_value = MagicMock()
    tree = S3Backend()
    result = tree.get_location("qc/subject123")
    assert result == f"s3://allen-data-views/data-asset-cache/{_VF}/qc/subject_id=subject123/data.pqt"


@patch("biodata_cache.backend.boto3.client")
def test_s3_get_location_platform_qc_partition(mock_boto3_client):
    mock_boto3_client.return_value = MagicMock()
    tree = S3Backend()
    result = tree.get_location("platform_qc/spim")
    assert result == f"s3://allen-data-views/data-asset-cache/{_VF}/platform_qc/platform=spim/data.pqt"


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_missing_object_returns_empty(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = _not_found_error()
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("read failed")
    result = S3Backend().read("nonexistent_table")
    assert result.empty
    assert isinstance(result, pd.DataFrame)


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_read_error_raises(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 1}
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("Connection reset by peer")
    with pytest.raises(Exception, match="Connection reset"):
        S3Backend().read("some_table")


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_multiple_tables(mock_boto3_client, mock_duckdb_query):
    mock_boto3_client.return_value = MagicMock()
    expected_df = pd.DataFrame(
        {"col1": [1, 2, 3, 4], "col2": ["a", "b", "c", "d"], "asset_name": ["table1", "table1", "table2", "table2"]}
    )
    mock_duckdb_query.return_value = expected_df
    result = S3Backend().read(["table1", "table2"])
    mock_duckdb_query.assert_called_once()
    query_call = mock_duckdb_query.call_args[0][0]
    assert "UNION ALL" in query_call
    assert "'table1' as asset_name" in query_call
    assert "'table2' as asset_name" in query_call
    pd.testing.assert_frame_equal(result, expected_df)


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_multiple_missing_returns_empty(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = _not_found_error()
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("read failed")
    result = S3Backend().read(["table1", "table2"])
    assert result.empty
    assert isinstance(result, pd.DataFrame)


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_multiple_read_error_raises(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 1}
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("Merge error")
    with pytest.raises(Exception, match="Merge error"):
        S3Backend().read(["table1", "table2"])


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_partitioned_missing_returns_empty(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {"KeyCount": 0}
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("read failed")
    result = S3Backend().read("qc/subject1")
    assert result.empty
    assert isinstance(result, pd.DataFrame)


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_partitioned_read_error_raises(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.list_objects_v2.return_value = {"KeyCount": 1}
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("read failed")
    with pytest.raises(Exception, match="read failed"):
        S3Backend().read("qc/subject1")


@patch("biodata_cache.backend.duckdb_query")
@patch("biodata_cache.backend.boto3.client")
def test_s3_scurry_non_404_head_error_raises(mock_boto3_client, mock_duckdb_query):
    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Internal Error"}}, "HeadObject"
    )
    mock_boto3_client.return_value = mock_s3
    mock_duckdb_query.side_effect = Exception("read failed")
    with pytest.raises(ClientError):
        S3Backend().read("some_table")
