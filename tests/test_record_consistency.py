"""Tests for the v2 duplicate-name record-consistency predicate."""

import pytest

from biodata_cache.record_consistency import (
    CHECK_KEY,
    DOCDB_VERSION,
    PROJECTION,
    V1_NAME_MISSING_V2_CHECK_KEY,
    V1_NAME_MISSING_V2_DOCDB_VERSION,
    V1_NAME_MISSING_V2_PROJECTION,
    evaluate_duplicate_names_v2,
    evaluate_v1_names_missing_v2,
)


def test_duplicate_name_v2_flags_every_group_member_with_complete_peers():
    """Every member of a duplicate group fails and lists all other IDs."""
    records = [
        {"_id": "v2-b", "name": "duplicate"},
        {"_id": "v2-c", "name": "duplicate"},
        {"_id": "v2-a", "name": "duplicate"},
    ]

    rows, summary = evaluate_duplicate_names_v2(records)

    assert [row["docdb_id"] for row in rows] == ["v2-a", "v2-b", "v2-c"]
    assert all(row["check_key"] == CHECK_KEY for row in rows)
    assert all(row["docdb_version"] == DOCDB_VERSION for row in rows)
    assert all(row["status"] == "fail" for row in rows)
    assert all(row["duplicate_group_count"] == 3 for row in rows)
    assert rows[0]["peer_docdb_ids"] == ["v2-b", "v2-c"]
    assert rows[1]["peer_docdb_ids"] == ["v2-a", "v2-c"]
    assert rows[2]["peer_docdb_ids"] == ["v2-a", "v2-b"]
    assert all("location" not in row for row in rows)
    assert summary.candidate_count == 3
    assert summary.processed_count == 3
    assert summary.failed_count == 3
    assert summary.duplicate_group_count == 1
    assert summary.is_complete


def test_unique_name_v2_passes():
    """A valid singleton is classified as pass with no peers."""
    rows, summary = evaluate_duplicate_names_v2([{"_id": "v2-a", "name": "unique"}])

    assert rows[0]["status"] == "pass"
    assert rows[0]["duplicate_group_count"] == 1
    assert rows[0]["peer_docdb_ids"] == []
    assert rows[0]["peer_names"] == []
    assert rows[0]["reason"] is None
    assert summary.failed_count == 0
    assert summary.duplicate_group_count == 0


def test_same_name_in_separate_input_populations_is_not_combined():
    """The v2 function labels only its own population as v2."""
    rows, summary = evaluate_duplicate_names_v2([{"_id": "v2-a", "name": "same"}])

    assert len(rows) == 1
    assert rows[0]["docdb_version"] == "v2"
    assert rows[0]["check_key"] == "docdb_duplicate_name_v2"
    assert summary.failed_count == 0


def test_missing_and_empty_names_are_skipped_not_flagged():
    """Missing or empty names cannot create a false duplicate finding."""
    rows, summary = evaluate_duplicate_names_v2(
        [
            {"_id": "v2-missing"},
            {"_id": "v2-null", "name": None},
            {"_id": "v2-empty", "name": ""},
            {"_id": "v2-valid", "name": "valid"},
        ]
    )

    assert [row["docdb_id"] for row in rows] == ["v2-valid"]
    assert summary.candidate_count == 4
    assert summary.processed_count == 1
    assert summary.skipped_count == 3
    assert summary.parse_failure_count == 0
    assert summary.is_complete


def test_malformed_records_are_counted_and_never_flagged():
    """Malformed IDs, names, and record objects become parse failures."""
    rows, summary = evaluate_duplicate_names_v2(
        [
            {"_id": "v2-good", "name": "same"},
            {"_id": "v2-bad-name", "name": 7},
            {"_id": 8, "name": "same"},
            ["not", "a", "record"],
        ]
    )

    assert len(rows) == 1
    assert rows[0]["status"] == "pass"
    assert summary.candidate_count == 4
    assert summary.processed_count == 1
    assert summary.parse_failure_count == 3
    assert not summary.is_complete


def test_matching_is_exact_without_case_or_whitespace_normalization():
    """Slice 1 does not merge case or surrounding-whitespace variants."""
    rows, summary = evaluate_duplicate_names_v2(
        [
            {"_id": "v2-a", "name": "Name"},
            {"_id": "v2-b", "name": "name"},
            {"_id": "v2-c", "name": " Name"},
        ]
    )

    assert all(row["status"] == "pass" for row in rows)
    assert summary.failed_count == 0
    assert summary.duplicate_group_count == 0


def test_duplicate_docdb_ids_fail_input_instead_of_becoming_peers():
    """Repeated source IDs indicate an invalid sweep, not a name duplicate."""
    with pytest.raises(ValueError, match="Duplicate DocDB ID.*v2-a"):
        evaluate_duplicate_names_v2(
            [
                {"_id": "v2-a", "name": "same"},
                {"_id": "v2-a", "name": "same"},
            ]
        )


def test_projection_is_explicitly_minimal():
    """The first check needs only the DocDB identity and name fields."""
    assert PROJECTION == {"_id": 1, "name": 1}


def test_v1_name_passes_when_at_least_one_exact_v2_match_exists():
    """One matching v2 name is sufficient, even when the name is duplicated."""
    rows, summary = evaluate_v1_names_missing_v2(
        [{"_id": "v1-a", "name": "shared"}],
        ["shared", "shared"],
    )

    assert rows == [
        {
            "check_key": V1_NAME_MISSING_V2_CHECK_KEY,
            "docdb_version": V1_NAME_MISSING_V2_DOCDB_VERSION,
            "docdb_id": "v1-a",
            "name": "shared",
            "status": "pass",
        }
    ]
    assert summary.failed_count == 0
    assert summary.is_complete


def test_v1_name_fails_when_no_v2_match_exists():
    """A valid v1 record fails when its exact name is absent from v2."""
    rows, summary = evaluate_v1_names_missing_v2(
        [{"_id": "v1-b", "name": "missing"}],
        {"present"},
    )

    assert rows[0]["status"] == "fail"
    assert summary.failed_count == 1


def test_v1_name_matching_is_exact_and_output_is_deterministic():
    """Case and whitespace remain significant and rows have stable ordering."""
    rows, summary = evaluate_v1_names_missing_v2(
        [
            {"_id": "v1-c", "name": "same"},
            {"_id": "v1-b", "name": " same"},
            {"_id": "v1-a", "name": "Same"},
        ],
        {"same"},
    )

    assert [row["docdb_id"] for row in rows] == ["v1-b", "v1-a", "v1-c"]
    assert [row["status"] for row in rows] == ["fail", "fail", "pass"]
    assert summary.failed_count == 2


def test_v1_missing_names_are_skipped_and_malformed_rows_are_incomplete():
    """The second check follows the first check's source-accounting policy."""
    rows, summary = evaluate_v1_names_missing_v2(
        [
            {"_id": "v1-missing"},
            {"_id": "v1-empty", "name": ""},
            {"_id": "v1-malformed", "name": 7},
            {"_id": "v1-valid", "name": "valid"},
        ],
        {"valid"},
    )

    assert [row["docdb_id"] for row in rows] == ["v1-valid"]
    assert summary.candidate_count == 4
    assert summary.processed_count == 1
    assert summary.skipped_count == 2
    assert summary.parse_failure_count == 1
    assert not summary.is_complete


def test_v1_duplicate_docdb_ids_fail_input():
    """Repeated v1 IDs indicate an invalid source sweep."""
    with pytest.raises(ValueError, match="Duplicate DocDB ID.*v1-a"):
        evaluate_v1_names_missing_v2(
            [
                {"_id": "v1-a", "name": "one"},
                {"_id": "v1-a", "name": "two"},
            ],
            set(),
        )


def test_v1_check_rejects_invalid_v2_reference_names():
    """The reference population must already contain only valid names."""
    with pytest.raises(ValueError, match="v2_names must contain only non-empty strings"):
        evaluate_v1_names_missing_v2([{"_id": "v1-a", "name": "name"}], {""})


def test_v1_projection_is_explicitly_minimal():
    """The second check needs only v1 identity and name fields."""
    assert V1_NAME_MISSING_V2_PROJECTION == {"_id": 1, "name": 1}
