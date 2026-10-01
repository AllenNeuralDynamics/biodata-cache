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
    record_consistency_results,
    record_consistency_results_columns,
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


def _run(previous=(None, None), force_full_rerun=False):
    results, checks = previous
    return build_snapshot(
        pd.DataFrame() if results is None else results,
        pd.DataFrame() if checks is None else checks,
        force_full_rerun=force_full_rerun,
    )


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
        _run()
    assert fake.fetches == 0


# --- snapshot ---


def test_results_and_checks_tables_describe_the_same_run(isolated, fake):
    isolated("shared_name", CROSS_CHECK)

    results, checks = _run()

    assert list(results.columns) == [column.name for column in record_consistency_results_columns()]
    assert list(checks.columns) == [column.name for column in record_consistency_checks_columns()]
    assert results[["record_id", "status"]].values.tolist() == [["id-1", "pass"], ["id-2", "fail"], ["id-3", "fail"]]
    assert set(results["record_kind"]) == {"fake_kind"}
    summary = checks.iloc[0].to_dict()
    assert summary["check_key"] == "shared_name"
    assert summary["check_description"] == "Fails records that share a name."
    assert summary["source"] == "fake"
    assert (summary["evaluated_count"], summary["failed_count"], summary["reused_count"], summary["skipped_count"]) == (
        3,
        2,
        0,
        0,
    )
    assert summary["check_eval_seconds"] >= 0 and summary["source_load_seconds"] >= 0
    assert set(results["checked_at"]) == {summary["checked_at"]}


def test_each_source_loads_once_for_every_check(isolated, fake):
    isolated("shared_name", CROSS_CHECK)
    isolated("name_starts_with_a", LOCAL_CHECK)

    results, checks = _run()

    assert fake.fetches == 1
    assert results["check_key"].tolist() == ["name_starts_with_a"] * 3 + ["shared_name"] * 3
    assert checks["check_key"].tolist() == ["name_starts_with_a", "shared_name"]
    assert checks["source_load_seconds"].nunique() == 1


def test_unchanged_records_reuse_results_and_changed_records_are_rechecked(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    first = _run()
    fake.rows = [
        ["id-1", "alpha", "s3://bucket/alpha", "t1"],
        ["id-2", "apple", None, "t2"],
        ["id-3", "beta", "s3://bucket/beta", None],
        ["id-4", "beta-2", None, "t1"],
    ]

    results, checks = _run(first)

    assert _evaluated(module)[-1] == ["id-2", "id-3", "id-4"]
    assert results.set_index("record_id")["status"].to_dict() == {
        "id-1": "pass",
        "id-2": "pass",
        "id-3": "fail",
        "id-4": "fail",
    }
    assert (checks.loc[0, "evaluated_count"], checks.loc[0, "reused_count"]) == (4, 1)


def test_deleted_records_leave_the_snapshot(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    first = _run()
    fake.rows = fake.rows[:1]

    assert _run(first)[0]["record_id"].tolist() == ["id-1"]


def test_changed_check_code_reevaluates_every_record(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    results, checks = _run()
    checks["check_hash"] = "older-code"

    _run((results, checks))

    assert _evaluated(module)[-1] == ["id-1", "id-2", "id-3"]


def test_missing_checks_table_reevaluates_every_record(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    results, _ = _run()

    _run((results, None))

    assert _evaluated(module)[-1] == ["id-1", "id-2", "id-3"]


def test_force_full_rerun_reevaluates_every_record(isolated, fake):
    module = isolated("name_starts_with_a", LOCAL_CHECK)
    first = _run()

    _run(first, force_full_rerun=True)

    assert _evaluated(module)[-1] == ["id-1", "id-2", "id-3"]


def test_checks_that_compare_across_records_never_reuse_results(isolated, fake):
    isolated("shared_name", CROSS_CHECK)
    first = _run()
    fake.rows = [row for row in fake.rows if row[0] != "id-3"]

    results, checks = _run(first)

    assert results.set_index("record_id")["status"].to_dict() == {"id-1": "pass", "id-2": "pass"}
    assert checks.loc[0, "reused_count"] == 0


def test_records_a_check_skips_have_no_result_row(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK.replace("PASS if", 'None if record["location"] is None else PASS if'))

    results, checks = _run()

    assert results[["record_id", "status"]].values.tolist() == [["id-1", "pass"], ["id-3", "fail"]]
    assert (checks.loc[0, "evaluated_count"], checks.loc[0, "skipped_count"]) == (2, 1)


def test_extra_source_fields_reach_checks_but_not_results(isolated):
    source = isolated(
        "extra_source", SOURCE_MODULE.replace('system = "memory"', 'system = "memory"\n        extra_fields = ("tag",)')
    )
    source.Fake.fetch = lambda self, previous: pd.DataFrame(
        [["id-1", "alpha", None, "t1", "keep"]], columns=[*framework.RECORD_FIELDS, "tag"]
    )
    isolated("tag_is_keep", LOCAL_CHECK.replace('record["name"].startswith("a")', 'record["tag"] == "keep"'))

    results, _ = _run()

    assert results["status"].tolist() == ["pass"]
    assert "tag" not in results.columns


def test_a_check_must_return_one_status_per_record(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK.replace("for record in records]", "for record in records][:1]"))

    with pytest.raises(ValueError, match="for each record"):
        _run()


def test_a_source_without_records_fails_the_snapshot(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    fake.rows = [[None, "no-id", None, None]]

    with pytest.raises(ValueError, match="no records"):
        _run()


# --- registered tables ---


def test_record_consistency_results_writes_both_tables_and_then_serves_them(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    results_table = registry.NAMES["record_consistency_results"]
    checks_table = registry.NAMES["record_consistency_checks"]

    results = record_consistency_results(force_update=True)

    pd.testing.assert_frame_equal(registry.BACKEND.read(results_table), results)
    assert record_consistency_results() is registry.BACKEND.read(results_table)
    assert record_consistency_checks() is registry.BACKEND.read(checks_table)
    assert record_consistency_checks()["check_key"].tolist() == ["name_starts_with_a"]


def test_record_consistency_checks_builds_the_snapshot_when_absent(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)

    checks = record_consistency_checks()

    assert checks["check_key"].tolist() == ["name_starts_with_a"]
    assert not registry.BACKEND.read(registry.NAMES["record_consistency_results"]).empty


def test_a_failed_run_writes_neither_table(isolated, fake):
    isolated("name_starts_with_a", LOCAL_CHECK)
    fake.rows = []

    with pytest.raises(ValueError):
        record_consistency_results(force_update=True)

    assert registry.BACKEND.read(registry.NAMES["record_consistency_results"]).empty
    assert registry.BACKEND.read(registry.NAMES["record_consistency_checks"]).empty
