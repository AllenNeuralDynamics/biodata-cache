"""Tests for record-consistency sources, checks, and the snapshot builder."""

import hashlib

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache import __version__
from biodata_cache.cache_table_helpers.record_consistency import framework
from biodata_cache.cache_table_helpers.record_consistency.framework import (
    build_snapshot,
    record_consistency_checks,
    record_consistency_checks_columns,
)

SOURCE_MODULE = """
    import pandas as pd
    from biodata_cache.cache_table_helpers.record_consistency.framework import RECORD_FIELDS, Source

    class Fake(Source):
        name = "fake"
        record_kind = "fake_kind"
        system = "memory"
        rows = []
        fetches = 0

        def fetch(self, previous):
            type(self).fetches += 1
            return pd.DataFrame(type(self).rows, columns=RECORD_FIELDS)
"""

LOCAL_CHECK = """
    from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check

    class NameStartsWithA(Check):
        description = "Fails records whose name does not start with a."
        source = "fake"
        evaluated = []

        def evaluate(self, records, **needed):
            type(self).evaluated.append([record["record_id"] for record in records])
            return [PASS if record["name"].startswith("a") else FAIL for record in records]
"""

CROSS_CHECK = """
    from collections import Counter
    from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check

    class SharedName(Check):
        description = "Fails records that share a name."
        source = "fake"
        compares_across_records = True

        def evaluate(self, records, **needed):
            counts = Counter(record["name"] for record in records)
            return [FAIL if counts[record["name"]] > 1 else PASS for record in records]
"""


@pytest.fixture
def fake(isolated):
    source = isolated("fake_source", SOURCE_MODULE).Fake
    source.rows = [
        ["id-1", "alpha", "s3://bucket/alpha", "t1"],
        ["id-2", "beta", None, "t1"],
        ["id-3", "beta", "s3://bucket/beta", None],
    ]
    return source


def _evaluated(module):
    return module.NameStartsWithA.evaluated


# --- registration ---


def test_check_key_hash_and_source_url_come_from_its_module(isolated, fake, tmp_path):
    isolated("name_starts_with_a", LOCAL_CHECK)

    check = framework.CHECKS["name_starts_with_a"]
    source = (tmp_path / "name_starts_with_a.py").read_bytes()
    assert check.key == "name_starts_with_a"
    assert check.hash == hashlib.sha256(source).hexdigest()[:12]
    assert check.source_url == (
        f"https://github.com/AllenNeuralDynamics/biodata-cache/blob/v{__version__}/src/name_starts_with_a.py#L4"
    )


@pytest.mark.parametrize(
    ("module_name", "body", "error"),
    [
        ("NotSnakeCase", LOCAL_CHECK, "snake_case"),
        (
            "no_description",
            LOCAL_CHECK.replace('description = "Fails records whose name does not start with a."', ""),
            "description",
        ),
    ],
)
def test_invalid_checks_are_rejected(isolated, fake, module_name, body, error):
    with pytest.raises((TypeError, ValueError), match=error):
        isolated(module_name, body)


def test_a_check_must_name_its_source(isolated, fake):
    with pytest.raises(TypeError, match="source"):
        isolated("no_source", LOCAL_CHECK.replace('source = "fake"', ""))


def test_a_source_must_declare_its_kind_and_register_once(isolated, fake):
    with pytest.raises(TypeError, match="record_kind"):
        isolated("kindless_source", SOURCE_MODULE.replace('record_kind = "fake_kind"', ""))
    with pytest.raises(ValueError, match="already registered"):
        isolated("fake_source_again", SOURCE_MODULE)


def test_a_check_key_registers_once(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)

    with pytest.raises(ValueError, match="already registered"):
        isolated("name_starts_with_a", LOCAL_CHECK)


def test_unknown_sources_are_rejected_before_loading(isolated, fake):
    isolated("needs_missing", CROSS_CHECK.replace('source = "fake"', 'source = "fake"\n        needs = ("missing",)'))

    with pytest.raises(ValueError, match="unknown sources"):
        build_snapshot(pd.DataFrame())
    assert fake.fetches == 0


# --- snapshot ---


def test_snapshot_rows_carry_record_and_check_metadata(isolated, fake):
    isolated("shared_name", CROSS_CHECK)

    snapshot = build_snapshot(pd.DataFrame())

    assert list(snapshot.columns) == [column.name for column in record_consistency_checks_columns()]
    assert snapshot[["record_id", "status"]].values.tolist() == [["id-1", "pass"], ["id-2", "fail"], ["id-3", "fail"]]
    assert set(snapshot["record_kind"]) == {"fake_kind"}
    assert set(snapshot["check_description"]) == {"Fails records that share a name."}
    assert snapshot["checked_at"].nunique() == 1


def test_each_source_loads_once_for_every_check(isolated, fake):
    isolated("shared_name", CROSS_CHECK)
    isolated("name_starts_with_a", LOCAL_CHECK)

    snapshot = build_snapshot(pd.DataFrame())

    assert fake.fetches == 1
    assert snapshot["check_key"].tolist() == ["name_starts_with_a"] * 3 + ["shared_name"] * 3


def test_unchanged_records_reuse_results_and_changed_records_are_rechecked(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    first = build_snapshot(pd.DataFrame())
    fake.rows = [
        ["id-1", "alpha", "s3://bucket/alpha", "t1"],
        ["id-2", "apple", None, "t2"],
        ["id-3", "beta", "s3://bucket/beta", None],
        ["id-4", "beta-2", None, "t1"],
    ]

    second = build_snapshot(first)

    assert _evaluated(module)[-1] == ["id-2", "id-3", "id-4"]
    assert second.set_index("record_id")["status"].to_dict() == {
        "id-1": "pass",
        "id-2": "pass",
        "id-3": "fail",
        "id-4": "fail",
    }


def test_deleted_records_leave_the_snapshot(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    first = build_snapshot(pd.DataFrame())
    fake.rows = fake.rows[:1]

    assert build_snapshot(first)["record_id"].tolist() == ["id-1"]


def test_changed_check_code_reevaluates_every_record(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    first = build_snapshot(pd.DataFrame())
    first["check_hash"] = "older-code"

    build_snapshot(first)

    assert _evaluated(module)[-1] == ["id-1", "id-2", "id-3"]


def test_force_full_rerun_reevaluates_every_record(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    first = build_snapshot(pd.DataFrame())

    build_snapshot(first, force_full_rerun=True)

    assert _evaluated(module)[-1] == ["id-1", "id-2", "id-3"]


def test_checks_that_compare_across_records_never_reuse_results(isolated, fake):
    isolated("shared_name", CROSS_CHECK)
    first = build_snapshot(pd.DataFrame())
    fake.rows = [row for row in fake.rows if row[0] != "id-3"]

    assert build_snapshot(first).set_index("record_id")["status"].to_dict() == {"id-1": "pass", "id-2": "pass"}


def test_a_check_must_return_one_status_per_record(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK.replace("for record in records]", "for record in records][:1]"))

    with pytest.raises(ValueError, match="for each record"):
        build_snapshot(pd.DataFrame())


def test_a_source_without_records_fails_the_snapshot(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    fake.rows = [[None, "no-id", None, None]]

    with pytest.raises(ValueError, match="no records"):
        build_snapshot(pd.DataFrame())


# --- record_consistency_checks ---


def test_record_consistency_checks_writes_and_then_serves_the_snapshot(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    table = registry.NAMES["record_consistency_checks"]

    snapshot = record_consistency_checks(force_update=True)

    pd.testing.assert_frame_equal(registry.BACKEND.read(table), snapshot)
    assert record_consistency_checks() is registry.BACKEND.read(table)


def test_record_consistency_checks_writes_nothing_when_a_source_fails(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    fake.rows = []

    with pytest.raises(ValueError):
        record_consistency_checks(force_update=True)

    assert registry.BACKEND.read(registry.NAMES["record_consistency_checks"]).empty
