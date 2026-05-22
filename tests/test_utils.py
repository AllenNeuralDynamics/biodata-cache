"""Unit tests for zombie_squirrel.utils module."""

from zombie_squirrel.utils import get_s3_cache_path, prefix_table_name


def test_prefix_table_name_basic():
    assert prefix_table_name("my_table") == "zs_my_table.pqt"

def test_prefix_table_name_empty_string():
    assert prefix_table_name("") == "zs_.pqt"

def test_prefix_table_name_single_char():
    assert prefix_table_name("a") == "zs_a.pqt"

def test_prefix_table_name_with_underscores():
    assert prefix_table_name("my_long_table_name") == "zs_my_long_table_name.pqt"

def test_prefix_table_name_with_numbers():
    assert prefix_table_name("table123") == "zs_table123.pqt"

def test_get_s3_cache_path_basic():
    assert get_s3_cache_path("zs_test.pqt") == "data-asset-cache/zs_test.pqt"

def test_get_s3_cache_path_various_names():
    assert get_s3_cache_path("zs_my_data.pqt") == "data-asset-cache/zs_my_data.pqt"
