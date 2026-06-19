"""Unit tests for scientist_rl_fib cache table."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.scientist.scientist_rl_fib import (
    _build_rows,
    _extract_brain_injections,
    _extract_coordinates,
    _extract_fiber_implants,
    _fetch_records,
    _get_fiber_injection_pairs,
    scientist_rl_fib,
    scientist_rl_fib_columns,
)


def _make_implant(fiber_name, acronym, translation):
    return {
        "object_type": "Probe implant",
        "implanted_device": {"name": fiber_name},
        "device_config": {
            "primary_targeted_structure": {"acronym": acronym},
            "transform": [
                {"object_type": "Translation", "translation": translation},
            ],
        },
    }


def _make_injection(acronym, virus_ids):
    return {
        "object_type": "Brain injection",
        "targeted_structure": {"acronym": acronym},
        "injection_materials": [
            {"tars_identifiers": {"virus_tars_id": vid}} for vid in virus_ids
        ],
    }


RECORD_ACB = {
    "name": "800001_2026-01-01_processed",
    "subject": {"subject_id": "800001"},
    "procedures": {
        "subject_procedures": [
            {
                "procedures": [
                    _make_implant("Fiber_0", "ACB", [1.0, -2.2, 0.0, 4.1]),
                    _make_implant("Fiber_1", "ACB", [1.0, 2.2, 0.0, 4.1]),
                    _make_injection("ACB", ["VIR001", "VIR002"]),
                ]
            }
        ]
    },
}

RECORD_PL = {
    "name": "800002_2026-01-01_processed",
    "subject": {"subject_id": "800002"},
    "procedures": {
        "subject_procedures": [
            {
                "procedures": [
                    _make_implant("Fiber_0", "PL", [2.0, 0.0, 0.0, 1.6]),
                    _make_injection("PL", ["VIR001"]),
                ]
            }
        ]
    },
}

RECORD_NO_MATCH = {
    "name": "800003_2026-01-01_processed",
    "subject": {"subject_id": "800003"},
    "procedures": {
        "subject_procedures": [
            {
                "procedures": [
                    _make_implant("Fiber_0", "PL", [2.0, 0.0, 0.0, 1.6]),
                    _make_injection("ACB", ["VIR001"]),
                ]
            }
        ]
    },
}


def test_extract_fiber_implants_basic():
    result = _extract_fiber_implants(RECORD_ACB)
    assert len(result) == 2
    assert result[0]["targeted_structure"] == "ACB"
    assert result[0]["coordinates"] == "AP=1.0, ML=2.2, D=4.1"
    assert result[1]["coordinates"] == "AP=1.0, ML=2.2, D=4.1"


def test_extract_fiber_implants_empty():
    assert _extract_fiber_implants({}) == []


def test_extract_fiber_implants_root_becomes_missing():
    record = {
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        {
                            "object_type": "Probe implant",
                            "implanted_device": {"name": "Fiber_0"},
                            "device_config": {
                                "primary_targeted_structure": {"acronym": "root"},
                                "transform": [],
                            },
                        }
                    ]
                }
            ]
        }
    }
    result = _extract_fiber_implants(record)
    assert result[0]["targeted_structure"] == "missing"


def test_extract_coordinates_valid():
    config = {"transform": [{"object_type": "Translation", "translation": [2.0, -0.8, 0.0, 1.6]}]}
    assert _extract_coordinates(config) == "AP=2.0, ML=0.8, D=1.6"


def test_extract_coordinates_no_translation():
    config = {"transform": [{"object_type": "Rotation", "angles": [5.0]}]}
    assert _extract_coordinates(config) == "missing"


def test_extract_coordinates_empty():
    assert _extract_coordinates({}) == "missing"


def test_extract_brain_injections_basic():
    result = _extract_brain_injections(RECORD_ACB)
    assert len(result) == 1
    assert result[0]["targeted_structure"] == "ACB"
    assert result[0]["viruses"] == ["VIR001", "VIR002"]


def test_extract_brain_injections_deduplicates_viruses():
    record = {
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        _make_injection("ACB", ["VIR001", "VIR001"]),
                    ]
                }
            ]
        }
    }
    result = _extract_brain_injections(record)
    assert result[0]["viruses"] == ["VIR001"]


def test_extract_brain_injections_empty():
    assert _extract_brain_injections({}) == []


def test_get_fiber_injection_pairs_matched():
    implants = [{"targeted_structure": "ACB", "coordinates": "AP=1, ML=2.2, D=4.1"}]
    injections = [{"targeted_structure": "ACB", "viruses": ["VIR001", "VIR002"]}]
    pairs = _get_fiber_injection_pairs(implants, injections)
    assert ("ACB", "AP=1, ML=2.2, D=4.1", "VIR001") in pairs
    assert ("ACB", "AP=1, ML=2.2, D=4.1", "VIR002") in pairs
    assert len(pairs) == 2


def test_get_fiber_injection_pairs_no_match():
    implants = [{"targeted_structure": "PL", "coordinates": "AP=2, ML=0, D=1.6"}]
    injections = [{"targeted_structure": "ACB", "viruses": ["VIR001"]}]
    pairs = _get_fiber_injection_pairs(implants, injections)
    assert pairs == []


def test_get_fiber_injection_pairs_deduplicates_viruses_across_injections():
    implants = [{"targeted_structure": "ACB", "coordinates": "AP=1, ML=2, D=4"}]
    injections = [
        {"targeted_structure": "ACB", "viruses": ["VIR001"]},
        {"targeted_structure": "ACB", "viruses": ["VIR001", "VIR002"]},
    ]
    pairs = _get_fiber_injection_pairs(implants, injections)
    viruses_seen = [v for _, _, v in pairs]
    assert viruses_seen.count("VIR001") == 1
    assert viruses_seen.count("VIR002") == 1


def test_get_fiber_injection_pairs_deduplicates_bilateral_implants():
    implants = [
        {"targeted_structure": "ACB", "coordinates": "AP=1.0, ML=2.2, D=4.1"},
        {"targeted_structure": "ACB", "coordinates": "AP=1.0, ML=2.2, D=4.1"},
    ]
    injections = [{"targeted_structure": "ACB", "viruses": ["VIR001"]}]
    pairs = _get_fiber_injection_pairs(implants, injections)
    assert len(pairs) == 1
    assert pairs[0] == ("ACB", "AP=1.0, ML=2.2, D=4.1", "VIR001")


def test_build_rows_different_coords_become_separate_rows():
    record = {
        "name": "800001_2026-01-01_processed",
        "subject": {"subject_id": "800001"},
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        _make_implant("Fiber_0", "ACB", [1.0, 2.2, 0.0, 4.1]),
                        _make_implant("Fiber_1", "ACB", [0.5, 1.5, 0.0, 3.0]),
                        _make_injection("ACB", ["VIR001"]),
                    ]
                }
            ]
        },
    }
    rows = _build_rows([record])
    coords = {r["coordinates"] for r in rows}
    assert coords == {"AP=1.0, ML=2.2, D=4.1", "AP=0.5, ML=1.5, D=3.0"}
    assert len(rows) == 2


def test_build_rows_basic():
    rows = _build_rows([RECORD_ACB])
    assert len(rows) == 2
    row_vir1 = next(r for r in rows if r["indicator"] == "VIR001")
    assert row_vir1["targeted_structure"] == "ACB"
    assert row_vir1["mouse_ids"] == ["800001"]
    assert row_vir1["mouse_count"] == 1
    assert row_vir1["session_count"] == 1
    assert row_vir1["coordinates"] == "AP=1.0, ML=2.2, D=4.1"


def test_build_rows_collapses_same_structure_across_subjects():
    record2 = {
        "name": "800002_2026-02-01_processed",
        "subject": {"subject_id": "800002"},
        "procedures": RECORD_ACB["procedures"],
    }
    rows = _build_rows([RECORD_ACB, record2])
    row_vir1 = next(r for r in rows if r["indicator"] == "VIR001")
    assert set(row_vir1["mouse_ids"]) == {"800001", "800002"}
    assert row_vir1["mouse_count"] == 2


def test_build_rows_counts_sessions_per_subject():
    session2 = {**RECORD_ACB, "name": "800001_2026-01-02_processed"}
    rows = _build_rows([RECORD_ACB, session2])
    row_vir1 = next(r for r in rows if r["indicator"] == "VIR001")
    assert row_vir1["session_count"] == 2


def test_build_rows_no_match_excluded():
    rows = _build_rows([RECORD_NO_MATCH])
    assert rows == []


def test_build_rows_multiple_structures():
    rows = _build_rows([RECORD_ACB, RECORD_PL])
    structures = {r["targeted_structure"] for r in rows}
    assert "ACB" in structures
    assert "PL" in structures


def test_build_rows_empty_records():
    assert _build_rows([]) == []


def test_scientist_rl_fib_raises_on_empty_cache():
    with patch("biodata_cache.cache_table_helpers.scientist.scientist_rl_fib.registry") as mock_reg:
        mock_reg.BACKEND.read.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="Cache is empty"):
            scientist_rl_fib(force_update=False)


def test_scientist_rl_fib_force_update_writes_cache():
    with patch("biodata_cache.cache_table_helpers.scientist.scientist_rl_fib.registry") as mock_reg:
        with patch(
            "biodata_cache.cache_table_helpers.scientist.scientist_rl_fib._fetch_records",
            return_value=[RECORD_ACB],
        ):
            mock_reg.BACKEND.read.return_value = pd.DataFrame()
            mock_reg.BACKEND.__class__.__name__ = "MemoryBackend"
            mock_reg.API_GATEWAY_HOST = "api.allenneuraldynamics.org"

            result = scientist_rl_fib(force_update=True)

            mock_reg.BACKEND.write.assert_called_once()
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 2


def test_scientist_rl_fib_returns_cached():
    cached = pd.DataFrame([{"targeted_structure": "ACB", "indicator": "VIR001"}])
    with patch("biodata_cache.cache_table_helpers.scientist.scientist_rl_fib.registry") as mock_reg:
        mock_reg.BACKEND.read.return_value = cached
        result = scientist_rl_fib(force_update=False)
        assert result.equals(cached)
        mock_reg.BACKEND.write.assert_not_called()


def test_scientist_rl_fib_columns_returns_expected_names():
    cols = scientist_rl_fib_columns()
    names = [c.name for c in cols]
    assert names == ["targeted_structure", "coordinates", "indicator", "mouse_ids", "mouse_count", "session_count"]


def test_fetch_records_calls_client():
    with patch(
        "biodata_cache.cache_table_helpers.scientist.scientist_rl_fib.MetadataDbClient"
    ) as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.retrieve_docdb_records.return_value = []
        result = _fetch_records()
        assert result == []
        mock_client.retrieve_docdb_records.assert_called_once()
