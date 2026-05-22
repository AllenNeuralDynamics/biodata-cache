"""Additional tests for forest module coverage."""

from unittest.mock import MagicMock, patch

from zombie_squirrel.forest import MemoryTree, S3Tree


def test_memory_tree_get_location_partitioned():
    tree = MemoryTree()
    result = tree.get_location("qc", partitioned=True)
    assert result == "qc/"


def test_memory_tree_plant():
    tree = MemoryTree()
    tree.plant("test.json", '{"key": "value"}')
    assert "test.json" in tree._json_store
    assert tree._json_store["test.json"] == '{"key": "value"}'


@patch("zombie_squirrel.forest.boto3")
def test_s3_get_location_partitioned(mock_boto3):
    mock_boto3.client.return_value = MagicMock()
    tree = S3Tree()
    result = tree.get_location("my_table", partitioned=True)
    assert "data-asset-cache/zs_my_table/" in result
    assert result.startswith("s3://")


@patch("zombie_squirrel.forest.boto3")
def test_s3_get_location_not_partitioned(mock_boto3):
    mock_boto3.client.return_value = MagicMock()
    tree = S3Tree()
    result = tree.get_location("my_table", partitioned=False)
    assert "data-asset-cache/" in result
    assert result.startswith("s3://")
    assert "zs_my_table/" not in result
