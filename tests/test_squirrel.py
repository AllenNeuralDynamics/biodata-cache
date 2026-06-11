"""Unit tests for zombie_squirrel.squirrel module."""

import json

import pytest

from zombie_squirrel.acorn_helpers.asset_basics import asset_basics_columns
from zombie_squirrel.acorn_helpers.qc import qc_columns
from zombie_squirrel.acorn_helpers.source_data import source_data_columns
from zombie_squirrel.acorn_helpers.unique_genotypes import unique_genotypes_columns
from zombie_squirrel.acorn_helpers.unique_project_names import unique_project_names_columns
from zombie_squirrel.acorn_helpers.unique_subject_ids import unique_subject_ids_columns
from zombie_squirrel.squirrel import Acorn, AcornType, Column, Squirrel


def _make_acorn(**kwargs):
    defaults = {
        "name": "test_acorn",
        "description": "A test acorn",
        "location": "s3://bucket/path/file.pqt",
        "partitioned": False,
        "type": AcornType.metadata,
        "columns": [Column(name="col1", description=""), Column(name="col2", description="")],
    }
    defaults.update(kwargs)
    return Acorn(**defaults)


# --- AcornType ---

def test_metadata_value():
    assert AcornType.metadata.value == "metadata"

def test_asset_value():
    assert AcornType.asset.value == "asset"

def test_event_value():
    assert AcornType.event.value == "event"

def test_realtime_value():
    assert AcornType.realtime.value == "realtime"

def test_all_types_count():
    assert len(AcornType) == 5


# --- Acorn ---

def test_acorn_basic_creation():
    acorn = _make_acorn()
    assert acorn.name == "test_acorn"
    assert acorn.location == "s3://bucket/path/file.pqt"
    assert acorn.partitioned is False
    assert acorn.partition_key is None
    assert acorn.type == AcornType.metadata
    assert acorn.columns == [Column(name="col1", description=""), Column(name="col2", description="")]

def test_acorn_partitioned_with_key():
    acorn = _make_acorn(partitioned=True, partition_key="subject_id", type=AcornType.asset)
    assert acorn.partitioned is True
    assert acorn.partition_key == "subject_id"

def test_acorn_partition_key_defaults_none():
    assert _make_acorn().partition_key is None

def test_acorn_asset_type():
    assert _make_acorn(type=AcornType.asset).type == AcornType.asset

def test_acorn_event_type():
    assert _make_acorn(type=AcornType.event).type == AcornType.event

def test_acorn_realtime_type():
    assert _make_acorn(type=AcornType.realtime).type == AcornType.realtime

def test_acorn_serialization_includes_type_value():
    data = json.loads(_make_acorn(type=AcornType.metadata).model_dump_json())
    assert data["type"] == "metadata"

def test_acorn_serialization_includes_all_fields():
    data = json.loads(_make_acorn().model_dump_json())
    for field in ("name", "description", "location", "partitioned", "partition_key", "type", "columns"):
        assert field in data

def test_acorn_columns_preserved():
    cols = [Column(name="_id", description=""), Column(name="_last_modified", description=""), Column(name="subject_id", description="")]
    assert _make_acorn(columns=cols).columns == cols


# --- Squirrel ---

def _squirrel_acorn(name="a"):
    return Acorn(
        name=name,
        description="A test acorn",
        location="s3://bucket/path.pqt",
        partitioned=False,
        type=AcornType.metadata,
        columns=[Column(name="col1", description="")],
    )

def test_squirrel_empty_acorns():
    assert Squirrel(acorns=[]).acorns == []

def test_squirrel_single_acorn():
    assert len(Squirrel(acorns=[_squirrel_acorn()]).acorns) == 1

def test_squirrel_multiple_acorns():
    assert len(Squirrel(acorns=[_squirrel_acorn(name=f"acorn_{i}") for i in range(3)]).acorns) == 3

def test_squirrel_serialization_top_level_key():
    data = json.loads(Squirrel(acorns=[_squirrel_acorn()]).model_dump_json())
    assert "acorns" in data
    assert len(data["acorns"]) == 1

def test_squirrel_serialization_roundtrip():
    acorn = Acorn(
        name="quality_control",
        description="QC data per subject",
        location="s3://bucket/qc/",
        partitioned=True,
        partition_key="subject_id",
        type=AcornType.asset,
        columns=[Column(name="name", description=""), Column(name="stage", description="")],
    )
    data = json.loads(Squirrel(acorns=[acorn]).model_dump_json())
    restored = Squirrel.model_validate(data)
    assert restored.acorns[0].name == "quality_control"
    assert restored.acorns[0].partition_key == "subject_id"
    assert restored.acorns[0].partitioned is True


# --- Column helpers ---

def test_unique_project_names_columns():
    cols = unique_project_names_columns()
    assert isinstance(cols, list)
    assert "project_name" in [c.name for c in cols]

def test_unique_subject_ids_columns():
    cols = unique_subject_ids_columns()
    assert isinstance(cols, list)
    assert "subject_id" in [c.name for c in cols]

def test_unique_genotypes_columns():
    cols = unique_genotypes_columns()
    assert isinstance(cols, list)
    assert "genotype" in [c.name for c in cols]

def test_asset_basics_columns():
    names = [c.name for c in asset_basics_columns()]
    for expected in ("_id", "_last_modified", "subject_id", "modalities", "project_name"):
        assert expected in names

def test_source_data_columns():
    assert "source_data" in [c.name for c in source_data_columns()]

def test_qc_columns():
    names = [c.name for c in qc_columns()]
    for expected in ("name", "stage", "status", "asset_name"):
        assert expected in names
