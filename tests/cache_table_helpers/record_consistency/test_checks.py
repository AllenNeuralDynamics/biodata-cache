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


def test_docdb_v1_name_missing_in_v2_fails_names_without_an_exact_v2_match():
    v1 = [{"record_id": str(index), "name": name} for index, name in enumerate(["kept", "Kept", "gone"])]
    v2 = [{"record_id": "v2", "name": "kept"}]

    assert CHECKS["docdb_v1_name_missing_in_v2"].evaluate(v1, docdb_v2=v2) == ["pass", "fail", "fail"]


def test_docdb_v1_name_missing_in_v2_compares_against_docdb_v2():
    check = CHECKS["docdb_v1_name_missing_in_v2"]
    assert (check.source, check.needs, check.compares_across_records) == ("docdb_v1", ("docdb_v2",), True)


def test_aind_open_data_prefix_missing_docdb_v2_matches_v2_locations_exactly():
    prefixes = [
        {"record_id": f"s3://aind-open-data/{name}", "name": name, "location": f"s3://aind-open-data/{name}"}
        for name in ["registered", "Registered", "unregistered"]
    ]
    v2 = [
        {"record_id": "a", "name": "registered", "location": "s3://aind-open-data/registered/"},
        {"record_id": "b", "name": "no-location", "location": None},
    ]

    assert CHECKS["aind_open_data_prefix_missing_docdb_v2"].evaluate(prefixes, docdb_v2=v2) == ["pass", "fail", "fail"]


def test_aind_open_data_prefix_missing_docdb_v2_compares_against_docdb_v2():
    check = CHECKS["aind_open_data_prefix_missing_docdb_v2"]
    assert (check.source, check.needs, check.compares_across_records) == (
        "aind_open_data_prefixes",
        ("docdb_v2",),
        True,
    )


def test_docdb_v2_code_ocean_location_mismatch_requires_every_visible_asset_to_match():
    def record(name, location, ids):
        return {"record_id": name, "name": name, "location": location, "code_ocean_ids": ids}

    records = [
        record("match", "s3://aind-open-data/match/", ["external"]),
        record("internal", "s3://codeocean-bucket/internal-id", ["internal-id"]),
        record("one-of-two", "s3://aind-open-data/match", ["external", "moved"]),
        record("internal-mismatch", "s3://codeocean-bucket/other-id", ["internal-id"]),
        record("no-location", None, ["external"]),
        record("invisible", "s3://aind-open-data/match", ["not-in-catalog"]),
        record("no-ids", "s3://aind-open-data/match", []),
    ]
    assets = [
        {"record_id": "external", "name": "a", "location": "s3://aind-open-data/match"},
        {"record_id": "moved", "name": "b", "location": "s3://aind-private-data/match"},
        {"record_id": "internal-id", "name": "c", "location": None},
    ]

    assert CHECKS["docdb_v2_code_ocean_location_mismatch"].evaluate(records, code_ocean_data_assets=assets) == [
        "pass",
        "pass",
        "fail",
        "fail",
        "fail",
        None,
        None,
    ]


def test_docdb_v2_code_ocean_location_mismatch_compares_against_code_ocean():
    check = CHECKS["docdb_v2_code_ocean_location_mismatch"]
    assert (check.source, check.needs, check.compares_across_records) == (
        "docdb_v2",
        ("code_ocean_data_assets",),
        True,
    )
