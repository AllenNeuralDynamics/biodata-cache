"""Tests for record-consistency check logic."""

from biodata_cache.cache_table_helpers.record_consistency.framework import CHECKS


def _statuses(key, names):
    return CHECKS[key].evaluate([{"record_id": str(index), "name": name} for index, name in enumerate(names)])


def test_docdb_duplicate_name_v2_fails_every_record_sharing_a_name():
    assert _statuses("docdb_duplicate_name_v2", ["a", "b", "a", "a"]) == ["fail", "pass", "fail", "fail"]


def test_docdb_duplicate_name_v2_matches_names_exactly():
    assert _statuses("docdb_duplicate_name_v2", ["Asset", "asset", "asset "]) == ["pass", "pass", "pass"]


def test_docdb_duplicate_name_v2_compares_across_records():
    assert CHECKS["docdb_duplicate_name_v2"].compares_across_records
