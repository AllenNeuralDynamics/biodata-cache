"""Additional tests for forest module coverage."""

from unittest.mock import MagicMock, patch

from zombie_squirrel.forest import MemoryTree, S3Tree
from zombie_squirrel.utils import ZS_VERSION

_VF = f"zs-v{ZS_VERSION}"


def test_memory_tree_get_location_partitioned():
    tree = MemoryTree()
    result = tree.get_location("qc", partitioned=True)
    assert result == f"{_VF}/qc/"


def test_memory_tree_plant():
    tree = MemoryTree()
    tree.plant("test.json", '{"key": "value"}')
    assert f"{_VF}/test.json" in tree._json_store
    assert tree._json_store[f"{_VF}/test.json"] == '{"key": "value"}'


@patch("zombie_squirrel.forest.boto3")
def test_s3_get_location_partitioned(mock_boto3):
    mock_boto3.client.return_value = MagicMock()
    tree = S3Tree()
    result = tree.get_location("my_table", partitioned=True)
    assert f"data-asset-cache/{_VF}/my_table/" in result
    assert result.startswith("s3://")


@patch("zombie_squirrel.forest.boto3")
def test_s3_get_location_not_partitioned(mock_boto3):
    mock_boto3.client.return_value = MagicMock()
    tree = S3Tree()
    result = tree.get_location("my_table", partitioned=False)
    assert f"data-asset-cache/{_VF}/my_table.pqt" in result
    assert result.startswith("s3://")
