"""Unit tests for platform_fib cache table."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.platform_fib import (
    _build_fib_rows,
    _extract_fiber_channel_entries,
    _extract_fiber_structure_map,
    _fetch_fib_records,
    platform_fib,
    platform_fib_columns,
)

RESOURCES = Path(__file__).parent.parent / "resources"


@pytest.fixture(scope="session")
def real_record():
    with open(RESOURCES / "fiber_example3.json") as f:
        return json.load(f)


# Minimal synthetic record: procedures use underscores ("Fiber_0"), connections
# use spaces ("Fiber 0") — the exact mismatch seen in production.
SYNTHETIC_RECORD = {
    "name": "test_asset_001",
    "procedures": {
        "subject_procedures": [
            {
                "procedures": [
                    {
                        "object_type": "Probe implant",
                        "implanted_device": {"name": "Fiber_0"},
                        "device_config": {"primary_targeted_structure": {"acronym": "ACB"}},
                    },
                    {
                        "object_type": "Probe implant",
                        "implanted_device": {"name": "Fiber_1"},
                        "device_config": {"primary_targeted_structure": {"acronym": "PIR"}},
                    },
                ]
            }
        ]
    },
    "acquisition": {
        "data_streams": [
            {
                "connections": [
                    # space-form target — must still match underscore-form fiber names
                    {"object_type": "Connection", "source_device": "Patch Cord 0", "target_device": "Fiber 0"},
                    {"object_type": "Connection", "source_device": "Patch Cord 1", "target_device": "Fiber 1"},
                    # detector connection — must NOT clobber patch cord mapping
                    {"object_type": "Connection", "source_device": "Patch Cord 0", "target_device": "Green CMOS"},
                ],
                "configurations": [
                    {
                        "object_type": "Patch cord config",
                        "device_name": "Patch Cord 0",
                        "channels": [
                            {"channel_name": "Fiber_0_Green", "intended_measurement": "calcium"},
                            {"channel_name": "Fiber_0_Isosbestic", "intended_measurement": "control"},
                        ],
                    },
                    {
                        "object_type": "Patch cord config",
                        "device_name": "Patch Cord 1",
                        "channels": [
                            {"channel_name": "Fiber_1_Green", "intended_measurement": "dopamine"},
                        ],
                    },
                ],
            }
        ]
    },
}


# --- _extract_fiber_structure_map ---


def test_extract_fiber_structure_map_known():
    result = _extract_fiber_structure_map(SYNTHETIC_RECORD)
    assert result == {"Fiber_0": "ACB", "Fiber_1": "PIR"}


def test_extract_fiber_structure_map_empty():
    assert _extract_fiber_structure_map({}) == {}


def test_extract_fiber_structure_map_missing_acronym_becomes_missing():
    record = {
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        {
                            "object_type": "Probe implant",
                            "implanted_device": {"name": "Fiber_0"},
                            "device_config": {},
                        }
                    ]
                }
            ]
        }
    }
    assert _extract_fiber_structure_map(record) == {"Fiber_0": "missing"}


def test_extract_fiber_structure_map_root_becomes_missing():
    record = {
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        {
                            "object_type": "Probe implant",
                            "implanted_device": {"name": "Fiber_0"},
                            "device_config": {"primary_targeted_structure": {"acronym": "root"}},
                        }
                    ]
                }
            ]
        }
    }
    assert _extract_fiber_structure_map(record) == {"Fiber_0": "missing"}


def test_extract_fiber_structure_map_skips_non_probe_implant():
    record = {"procedures": {"subject_procedures": [{"procedures": [{"object_type": "Headframe"}]}]}}
    assert _extract_fiber_structure_map(record) == {}


def test_extract_fiber_structure_map_real_example(real_record):
    result = _extract_fiber_structure_map(real_record)
    assert "Fiber_0" in result
    assert result["Fiber_0"] == "PL"
    assert result["Fiber_2"] == "ACB"


# --- _extract_fiber_channel_entries ---


def test_extract_fiber_channel_entries_resolves_all_fibers():
    fiber_names = {"Fiber_0", "Fiber_1"}
    entries = _extract_fiber_channel_entries(SYNTHETIC_RECORD, fiber_names)
    fibers = [e[0] for e in entries]
    assert "missing" not in fibers
    assert "Fiber_0" in fibers
    assert "Fiber_1" in fibers


def test_extract_fiber_channel_entries_space_underscore_mismatch():
    """Connections use 'Fiber 0' (space); fiber_names has 'Fiber_0' (underscore). Must match."""
    fiber_names = {"Fiber_0"}
    entries = _extract_fiber_channel_entries(SYNTHETIC_RECORD, fiber_names)
    cord0 = [e for e in entries if e[1] == "Patch Cord 0"]
    assert len(cord0) > 0
    assert cord0[0][0] == "Fiber_0"


def test_extract_fiber_channel_entries_detector_connection_does_not_clobber():
    """Patch Cord 0 also connects to Green CMOS — must not overwrite the fiber mapping."""
    fiber_names = {"Fiber_0", "Fiber_1"}
    entries = _extract_fiber_channel_entries(SYNTHETIC_RECORD, fiber_names)
    for fiber, patch_cord, _, _ in entries:
        if patch_cord == "Patch Cord 0":
            assert fiber == "Fiber_0"


def test_extract_fiber_channel_entries_returns_all_channels():
    fiber_names = {"Fiber_0", "Fiber_1"}
    entries = _extract_fiber_channel_entries(SYNTHETIC_RECORD, fiber_names)
    # 2 channels on Patch Cord 0, 1 on Patch Cord 1
    assert len(entries) == 3


def test_extract_fiber_channel_entries_null_intended_measurement_becomes_missing():
    record = {
        "acquisition": {
            "data_streams": [
                {
                    "connections": [{"source_device": "Patch Cord 0", "target_device": "Fiber_0"}],
                    "configurations": [
                        {
                            "object_type": "Patch cord config",
                            "device_name": "Patch Cord 0",
                            "channels": [{"channel_name": "Fiber_0_Green", "intended_measurement": None}],
                        }
                    ],
                }
            ]
        }
    }
    entries = _extract_fiber_channel_entries(record, {"Fiber_0"})
    assert entries[0][3] == "missing"


def test_extract_fiber_channel_entries_skips_patch_cord_with_no_procedure_fiber():
    """Patch cord connected to a fiber not in procedures should produce no rows."""
    record = {
        "acquisition": {
            "data_streams": [
                {
                    "connections": [
                        {"source_device": "Patch Cord 0", "target_device": "Fiber 0"},
                    ],
                    "configurations": [
                        {
                            "object_type": "Patch cord config",
                            "device_name": "Patch Cord 0",
                            "channels": [{"channel_name": "Fiber_0_Green", "intended_measurement": "calcium"}],
                        }
                    ],
                }
            ]
        }
    }
    # fiber_names is empty — Fiber_0 not in procedures
    entries = _extract_fiber_channel_entries(record, set())
    assert entries == []


def test_extract_fiber_channel_entries_empty_acquisition():
    assert _extract_fiber_channel_entries({}, {"Fiber_0"}) == []


def test_extract_fiber_channel_entries_real_example(real_record):
    fiber_names = set(_extract_fiber_structure_map(real_record).keys())
    entries = _extract_fiber_channel_entries(real_record, fiber_names)
    assert len(entries) > 0
    fibers = {e[0] for e in entries}
    assert "missing" not in fibers
    assert "Fiber_0" in fibers


# --- _build_fib_rows ---


def test_build_fib_rows_one_row_per_fiber_channel():
    rows = _build_fib_rows([SYNTHETIC_RECORD])
    # 2 channels on Fiber_0, 1 on Fiber_1
    assert len(rows) == 3


def test_build_fib_rows_keys():
    rows = _build_fib_rows([SYNTHETIC_RECORD])
    assert set(rows[0].keys()) == {
        "asset_name",
        "fiber",
        "patch_cord",
        "channel",
        "intended_measurement",
        "targeted_structure",
    }


def test_build_fib_rows_targeted_structure():
    rows = _build_fib_rows([SYNTHETIC_RECORD])
    by_fiber = {r["fiber"]: r["targeted_structure"] for r in rows}
    assert by_fiber["Fiber_0"] == "ACB"
    assert by_fiber["Fiber_1"] == "PIR"


def test_build_fib_rows_empty():
    assert _build_fib_rows([]) == []


def test_build_fib_rows_multiple_assets():
    record2 = {**SYNTHETIC_RECORD, "name": "test_asset_002"}
    rows = _build_fib_rows([SYNTHETIC_RECORD, record2])
    names = {r["asset_name"] for r in rows}
    assert "test_asset_001" in names
    assert "test_asset_002" in names


def test_build_fib_rows_real_example(real_record):
    rows = _build_fib_rows([real_record])
    assert len(rows) > 0
    df = pd.DataFrame(rows)
    assert "missing" not in df["fiber"].values
    assert not df["targeted_structure"].isna().any()


# --- _fetch_fib_records ---


@patch("biodata_cache.cache_table_helpers.platform_fib.MetadataDbClient")
def test_fetch_fib_records_batches(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = []
    _fetch_fib_records([f"asset_{i}" for i in range(250)])
    assert mock_client.retrieve_docdb_records.call_count == 3


@patch("biodata_cache.cache_table_helpers.platform_fib.MetadataDbClient")
def test_fetch_fib_records_combines_batches(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.side_effect = [[{"name": "a"}], [{"name": "b"}]]
    result = _fetch_fib_records([f"asset_{i}" for i in range(150)])
    assert len(result) == 2


# --- platform_fib ---


@patch("biodata_cache.cache_table_helpers.platform_fib.registry.BACKEND")
def test_platform_fib_empty_cache_raises(mock_backend):
    mock_backend.read.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        platform_fib(force_update=False)


@patch("biodata_cache.cache_table_helpers.platform_fib.registry.BACKEND")
def test_platform_fib_cache_hit(mock_backend):
    cached = pd.DataFrame(
        {
            "asset_name": ["x"],
            "fiber": ["Fiber_0"],
            "patch_cord": ["Patch Cord 0"],
            "channel": ["Fiber_0_Green"],
            "intended_measurement": ["calcium"],
            "targeted_structure": ["ACB"],
        }
    )
    mock_backend.read.return_value = cached
    result = platform_fib(force_update=False)
    assert len(result) == 1


@patch("biodata_cache.cache_table_helpers.platform_fib.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.platform_fib.asset_basics")
@patch("biodata_cache.cache_table_helpers.platform_fib.registry.BACKEND")
def test_platform_fib_force_update(mock_backend, mock_basics, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_basics.return_value = pd.DataFrame({"name": ["test_asset_001"], "modalities": [np.array(["fib"])]})
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [SYNTHETIC_RECORD]
    result = platform_fib(force_update=True)
    assert len(result) > 0
    mock_backend.write.assert_called_once()


@patch("biodata_cache.cache_table_helpers.platform_fib.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.platform_fib.asset_basics")
@patch("biodata_cache.cache_table_helpers.platform_fib.registry.BACKEND")
def test_platform_fib_filters_fib_modality(mock_backend, mock_basics, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_basics.return_value = pd.DataFrame(
        {"name": ["fib_asset", "spim_asset"], "modalities": [np.array(["fib"]), np.array(["SPIM"])]}
    )
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = []
    platform_fib(force_update=True)
    call_args = mock_client.retrieve_docdb_records.call_args
    if call_args:
        names_filter = call_args[1]["filter_query"]["name"]["$in"]
        assert "fib_asset" in names_filter
        assert "spim_asset" not in names_filter


# --- platform_fib_columns ---


def test_platform_fib_columns_names():
    names = [c.name for c in platform_fib_columns()]
    assert "asset_name" in names
    assert "fiber" in names
    assert "patch_cord" in names
    assert "channel" in names
    assert "intended_measurement" in names
    assert "targeted_structure" in names
