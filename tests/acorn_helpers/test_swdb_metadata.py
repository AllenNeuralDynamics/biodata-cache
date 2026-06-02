"""Unit tests for swdb_metadata acorn."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import zombie_squirrel.acorns as acorns
from zombie_squirrel.acorn_helpers.swdb_metadata import (
    DATASETS,
    swdb_metadata,
    swdb_metadata_columns,
    _parse_dates,
)
from zombie_squirrel.forest import MemoryTree


@pytest.fixture(autouse=True)
def memory_tree():
    acorns.TREE = MemoryTree()


def test_datasets_list():
    assert "v1dd" in DATASETS
    assert "bci" in DATASETS
    assert "dynamic_foraging" in DATASETS
    assert "np_ultra" in DATASETS


def test_invalid_dataset_raises():
    with pytest.raises(ValueError, match="Unknown dataset"):
        swdb_metadata("nonexistent")


def test_empty_cache_raises():
    with pytest.raises(ValueError, match="Cache is empty"):
        swdb_metadata("v1dd", force_update=False)


def test_cache_hit():
    cached = pd.DataFrame({"name": ["asset_1"], "subject_id": ["sub1"]})
    acorns.TREE.hide("swdb_metadata/v1dd", cached)
    df = swdb_metadata("v1dd", force_update=False)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "asset_1"


@patch("zombie_squirrel.acorn_helpers.swdb_metadata.MetadataDbClient")
def test_force_update_replaces_cache(mock_client_class):
    cached = pd.DataFrame({"name": ["old_asset"], "subject_id": ["sub1"]})
    acorns.TREE.hide("swdb_metadata/v1dd", cached)

    full_record = {
        "_id": "abc",
        "name": "v1dd_asset",
        "data_description": {
            "subject_id": "sub1",
            "project_name": "V1 Deep Dive",
            "modalities": [{"name": "SPIM"}],
            "tags": ["Column 1", "Volume 2"],
        },
        "subject": {"subject_details": {"genotype": "wt", "date_of_birth": "2024-01-01", "sex": "M"}},
        "acquisition": {"acquisition_start_time": "2025-03-01T10:00:00"},
    }
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.side_effect = [[{"_id": "abc"}], [full_record]]

    df = swdb_metadata("v1dd", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "v1dd_asset"
    assert df.iloc[0]["column"] == 1
    assert df.iloc[0]["volume"] == 2
    assert not df.iloc[0]["golden_mouse"]


@patch("zombie_squirrel.acorn_helpers.swdb_metadata.MetadataDbClient")
def test_v1dd_golden_mouse(mock_client_class):
    full_record = {
        "_id": "abc",
        "name": "v1dd_asset",
        "data_description": {
            "subject_id": "409828",
            "project_name": "V1 Deep Dive",
            "modalities": [{"name": "SPIM"}],
            "tags": ["Column 3", "Volume 5"],
        },
        "subject": {"subject_details": {"genotype": "wt", "date_of_birth": "2024-01-01", "sex": "M"}},
        "acquisition": {"acquisition_start_time": "2025-03-01T10:00:00"},
    }
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.side_effect = [[{"_id": "abc"}], [full_record]]
    df = swdb_metadata("v1dd", force_update=True)
    assert df.iloc[0]["golden_mouse"]


@patch("zombie_squirrel.acorn_helpers.swdb_metadata.MetadataDbClient")
def test_dynamic_foraging_deduplication(mock_client_class):
    record = {
        "_id": "abc",
        "name": "asset_1",
        "data_description": {
            "subject_id": "sub1",
            "project_name": "Behavior Platform",
            "modalities": [{"name": "behavior"}],
        },
        "subject": {"genotype": "wt", "date_of_birth": "2024-01-01", "sex": "F"},
        "acquisition": {
            "acquisition_type": "Coupled Baiting",
            "acquisition_start_time": "2025-04-01T09:00:00",
        },
        "quality_control": {"status": {"video": "Pass", "behavior": "Pass"}},
        "session": {
            "stimulus_epochs": [{"trials_total": 200, "trials_rewarded": 150}],
        },
    }
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.side_effect = [[{"_id": "abc"}, {"_id": "abc"}], [record, record]]
    df = swdb_metadata("dynamic_foraging", force_update=True)
    assert len(df) == 1


@patch("zombie_squirrel.acorn_helpers.swdb_metadata.MetadataDbClient")
def test_bci_problem_assets_excluded(mock_client_class):
    def _bci_record(_id, name, subject_id, session_time):
        return {
            "_id": _id,
            "name": name,
            "data_description": {
                "subject_id": subject_id,
                "project_name": "BCI",
                "modalities": [{"name": "ophys"}],
            },
            "subject": {"genotype": "wt", "date_of_birth": "2024-06-01", "sex": "M"},
            "acquisition": {
                "acquisition_type": "BCI single neuron stim",
                "acquisition_start_time": session_time,
            },
            "procedures": {"subject_procedures": [{"procedures": [{"injection_materials": [{"name": "AAV"}]}]}]},
            "session": {
                "data_streams": [{"stack_parameters": {"targeted_structure": "V1"}, "ophys_fovs": [{"notes": "note"}]}],
                "stimulus_epochs": [],
            },
        }

    problem = _bci_record(
        "abc",
        "single-plane-ophys_731015_2025-01-28_17-40-57_processed_2025-08-04_04-38-08",
        "731015",
        "2025-01-28T17:40:57",
    )
    good = _bci_record("def", "good_asset", "sub2", "2025-05-01T12:00:00")
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.side_effect = [[{"_id": "abc"}, {"_id": "def"}], [problem, good]]
    df = swdb_metadata("bci", force_update=True)
    assert "single-plane-ophys_731015" not in df["name"].values
    assert "good_asset" in df["name"].values


@patch("zombie_squirrel.acorn_helpers.swdb_metadata.MetadataDbClient")
def test_np_ultra_session_types(mock_client_class):
    def _np_record(_id, name, session_time):
        return {
            "_id": _id,
            "name": name,
            "data_description": {
                "subject_id": "sub1",
                "project_name": "NP Ultra and Psychedelics",
                "modalities": [{"name": "ecephys"}],
            },
            "subject": {"genotype": "wt", "date_of_birth": "2024-01-15", "sex": "M"},
            "acquisition": {"acquisition_start_time": session_time},
            "session": {"stimulus_epochs": []},
        }

    records = [
        _np_record("a1", "np_asset_1", "2025-02-01T10:00:00"),
        _np_record("a2", "np_asset_2", "2025-03-01T10:00:00"),
    ]
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.side_effect = [[{"_id": "a1"}, {"_id": "a2"}], records]
    df = swdb_metadata("np_ultra", force_update=True)
    assert list(df["session_type"]) == ["saline", "psilocybin"]
    assert isinstance(df.iloc[0]["stimulus_types"], list)


def test_parse_dates():
    df = pd.DataFrame({
        "session_time": ["2025-06-01T14:30:00"],
        "date_of_birth": ["2024-01-15"],
    })
    result = _parse_dates(df)
    assert result.iloc[0]["age"] == (result.iloc[0]["session_date"] - result.iloc[0]["date_of_birth"]).days


def test_swdb_metadata_columns_v1dd():
    cols = swdb_metadata_columns("v1dd")
    names = [c.name for c in cols]
    assert "golden_mouse" in names
    assert "column" in names
    assert "volume" in names


def test_swdb_metadata_columns_bci():
    cols = swdb_metadata_columns("bci")
    names = [c.name for c in cols]
    assert "virus" in names
    assert "ophys_fov" in names
    assert "session_number" in names


def test_swdb_metadata_columns_dynamic_foraging():
    cols = swdb_metadata_columns("dynamic_foraging")
    names = [c.name for c in cols]
    assert "trials_total" in names
    assert "trials_rewarded" in names


def test_swdb_metadata_columns_np_ultra():
    cols = swdb_metadata_columns("np_ultra")
    names = [c.name for c in cols]
    assert "session_type" in names
    assert "stimulus_types" in names
    assert "notes" in names


def test_swdb_metadata_columns_unknown():
    assert swdb_metadata_columns("unknown") == []
