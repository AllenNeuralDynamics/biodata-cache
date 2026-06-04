"""Unit tests for zombie_squirrel.utils module."""

from zombie_squirrel.utils import get_s3_cache_path, normalize_experimenters, normalize_instrument_id, normalize_name, parse_experimenters, prefix_table_name


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


def test_normalize_instrument_id_underscore_separator():
    assert normalize_instrument_id("AIND_MESO2_20240115") == "MESO2"

def test_normalize_instrument_id_with_location_prefix():
    assert normalize_instrument_id("HQ_NP3_20231005") == "NP3"

def test_normalize_instrument_id_hyphen_separator():
    assert normalize_instrument_id("HQ-NP3_20231005") == "NP3"

def test_normalize_instrument_id_already_short():
    assert normalize_instrument_id("MESO2") == "MESO2"

def test_normalize_instrument_id_none():
    assert normalize_instrument_id(None) == ""

def test_normalize_instrument_id_iso_date():
    assert normalize_instrument_id("AIND_MESO2_2024-01-15") == "MESO2"

def test_normalize_instrument_id_short_year():
    assert normalize_instrument_id("AIND_NP3_231005") == "NP3"

def test_normalize_instrument_id_strips_internal_separators():
    assert normalize_instrument_id("AIND_NP-3_20240115") == "NP3"

def test_normalize_instrument_id_empty_string():
    assert normalize_instrument_id("") == ""


def test_normalize_name_dots():
    assert normalize_name("anna.katelyn.mcdougal") == "Anna Katelyn Mcdougal"

def test_normalize_name_single():
    assert normalize_name("nick.ponvert") == "Nick Ponvert"

def test_normalize_name_extra_spaces():
    assert normalize_name("  john  doe  ") == "John Doe"

def test_normalize_name_underscores():
    assert normalize_name("john_doe") == "John Doe"

def test_normalize_name_empty():
    assert normalize_name("") == ""

def test_normalize_name_already_clean():
    assert normalize_name("John Doe") == "John Doe"


def test_parse_experimenters_basic():
    assert parse_experimenters("nick.ponvert, anna.katelyn.mcdougal") == ["Nick Ponvert", "Anna Katelyn Mcdougal"]

def test_parse_experimenters_deduplicates():
    assert parse_experimenters("john.doe, John Doe") == ["John Doe"]

def test_parse_experimenters_none():
    assert parse_experimenters(None) == []

def test_parse_experimenters_empty():
    assert parse_experimenters("") == []

def test_parse_experimenters_single():
    assert parse_experimenters("nick.ponvert") == ["Nick Ponvert"]

def test_parse_experimenters_whitespace_only():
    assert parse_experimenters("   ") == []


def test_normalize_experimenters_list_of_names():
    assert normalize_experimenters(["nick.ponvert", "anna.katelyn.mcdougal"]) == ["Anna Katelyn Mcdougal", "Nick Ponvert"]

def test_normalize_experimenters_comma_separated_element():
    assert normalize_experimenters(["nick.ponvert, anna.katelyn.mcdougal"]) == ["Anna Katelyn Mcdougal", "Nick Ponvert"]

def test_normalize_experimenters_deduplicates_across_elements():
    assert normalize_experimenters(["john.doe", "John Doe", "john.doe"]) == ["John Doe"]

def test_normalize_experimenters_empty_list():
    assert normalize_experimenters([]) == []

def test_normalize_experimenters_skips_none_and_empty():
    assert normalize_experimenters([None, "", "nick.ponvert"]) == ["Nick Ponvert"]

def test_normalize_experimenters_sorted():
    assert normalize_experimenters(["zoe.smith", "anna.jones"]) == ["Anna Jones", "Zoe Smith"]
