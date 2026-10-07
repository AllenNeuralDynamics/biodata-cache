"""Unit tests for platform_smartspim_fiber_ccf cache table."""

from unittest.mock import patch

import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.platform_smartspim_fiber_ccf import (
    COLUMNS,
    _build_rows,
    _fetch_records,
    _index,
    platform_smartspim_fiber_ccf,
    platform_smartspim_fiber_ccf_columns,
)

MODULE = "biodata_cache.cache_table_helpers.platform_smartspim_fiber_ccf"
NAME = "SmartSPIM_820651_2026-04-08_20-37-16_stitched_2026-05-19_07-46-11"


def _implant(name, acronym="ACB", device_type="Fiber probe"):
    return {
        "object_type": "Probe implant",
        "implanted_device": {"object_type": device_type, "name": name},
        "device_config": {"primary_targeted_structure": {"acronym": acronym}},
    }


def _record(metrics=None):
    return {
        "name": NAME,
        "subject": {"subject_id": "820651"},
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        _implant("Fiber 0"),
                        _implant("Fiber 1", "SUB"),
                        _implant("A", device_type="Ephys probe"),
                    ]
                }
            ]
        },
        "quality_control": {"metrics": metrics or []},
    }


def _metric(name, value, status="Pass"):
    return {
        "name": name,
        "value": value,
        "reference": "https://ng/#!ccf",
        "status_history": [
            {"status": "Pending", "evaluator": "a", "timestamp": "t0"},
            {"status": status, "evaluator": "b", "timestamp": "t1"},
        ],
    }


def test_index_coerces_integral_values_only():
    assert _index(12) == 12
    assert _index(12.0) == 12
    assert _index(" 7 ") == 7
    assert _index(12.5) is None
    assert _index("x") is None
    assert _index(None) is None
    assert _index(True) is None


def test_rows_per_fiber_with_annotations():
    rows = _build_rows(
        [
            _record(
                [
                    _metric("Fiber 0 CCF Location", {"AP": 210, "ML": 150, "DV": 180}),
                    _metric("Fiber 1 CCF Location", 'json:{"AP": 1, "ML": null, "DV": "3"}', status="Pending"),
                ]
            )
        ]
    )
    assert [r["fiber"] for r in rows] == ["Fiber 0", "Fiber 1"]
    assert rows[0] == {
        "subject_id": "820651",
        "name": NAME,
        "fiber": "Fiber 0",
        "targeted_structure": "ACB",
        "ap": 210,
        "ml": 150,
        "dv": 180,
        "status": "Pass",
        "evaluator": "b",
        "status_timestamp": "t1",
        "ccf_link": "https://ng/#!ccf",
    }
    assert (rows[1]["ap"], rows[1]["ml"], rows[1]["dv"], rows[1]["status"]) == (1, None, 3, "Pending")


def test_unannotated_fibers_still_listed():
    rows = _build_rows([_record()])
    assert len(rows) == 2
    assert all(r["ap"] is None and r["status"] is None and r["ccf_link"] is None for r in rows)


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_fetch_records_filters_stitched_spim_fiber_assets(mock_client_class):
    client = mock_client_class.return_value
    client.retrieve_docdb_records.return_value = [_record()]
    assert _fetch_records() == [_record()]
    query = client.retrieve_docdb_records.call_args.kwargs["filter_query"]
    assert query["data_description.modalities.abbreviation"] == "SPIM"
    assert query["name"] == {"$regex": "_stitched_"}
    assert query["procedures.subject_procedures.procedures.implanted_device.object_type"] == "Fiber probe"


@patch(f"{MODULE}._fetch_records")
@patch(f"{MODULE}.registry")
def test_table_builds_and_writes(mock_registry, mock_fetch):
    mock_registry.NAMES = {"smartspim_fiber_ccf": "platform_smartspim_fiber_ccf"}
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    mock_fetch.return_value = [_record([_metric("Fiber 0 CCF Location", {"AP": 1, "ML": 2, "DV": 3})])]
    df = platform_smartspim_fiber_ccf(force_update=True)
    assert list(df.columns) == COLUMNS
    assert str(df["ap"].dtype) == "Int64"
    assert df["ap"].tolist()[0] == 1 and pd.isna(df["ap"].tolist()[1])
    mock_registry.BACKEND.write.assert_called_once()


@patch(f"{MODULE}.registry")
def test_empty_cache_without_force_raises(mock_registry):
    mock_registry.NAMES = {"smartspim_fiber_ccf": "platform_smartspim_fiber_ccf"}
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    with pytest.raises(ValueError):
        platform_smartspim_fiber_ccf()


def test_columns_match_frame():
    assert [c.name for c in platform_smartspim_fiber_ccf_columns()] == COLUMNS
