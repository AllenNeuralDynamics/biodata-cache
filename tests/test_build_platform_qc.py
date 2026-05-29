"""Unit tests for build_platform_qc script."""

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import duckdb

from scripts.build_platform_qc import (
    PLATFORMS,
    S3_BUCKET,
    S3_PREFIX,
    QC_PREFIX,
    build_platform_table,
    list_qc_subject_ids,
    upload_parquet,
)


@pytest.fixture
def sample_asset_basics():
    return pd.DataFrame({
        "name": ["spim_asset_1", "spim_asset_2", "fib_asset_1", "vr_asset_1"],
        "subject_id": ["subj1", "subj1", "subj2", "subj3"],
        "modalities": ["SPIM", "SPIM", "fib", "ecephys"],
        "instrument_id": ["rig_a", "rig_b", None, "rig_c"],
        "experimenters": ["Alice, Bob", "Charlie", None, "Dave"],
        "acquisition_start_time": ["2025-06-01T10:00:00", "2025-06-02T10:00:00", "2025-06-03T10:00:00", "2025-06-04T10:00:00"],
        "acquisition_type": [None, None, None, "AindVrForaging"],
    })


@pytest.fixture
def sample_qc_data():
    return pd.DataFrame({
        "name": ["Metric A", "Metric B", "Metric A", "Metric C"],
        "modality": ["SPIM", "SPIM", "SPIM", "fib"],
        "stage": ["Processing", "Processing", "Raw data", "Processing"],
        "value": ["ok", "bad", "ok", "ok"],
        "status": ["Pass", "Fail", "Pass", "Pass"],
        "asset_name": ["spim_asset_1", "spim_asset_1", "spim_asset_2", "fib_asset_1"],
        "subject_id": ["subj1", "subj1", "subj1", "subj2"],
        "timestamp": pd.to_datetime(["2025-06-01", "2025-06-01", "2025-06-02", "2025-06-03"]),
    })


def test_list_qc_subject_ids():
    mock_client = MagicMock()
    mock_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [
            {"Key": f"{QC_PREFIX}subj1.pqt"},
            {"Key": f"{QC_PREFIX}subj2.pqt"},
            {"Key": f"{QC_PREFIX}subj3.pqt"},
        ]}
    ]
    result = list_qc_subject_ids(mock_client)
    assert result == {"subj1", "subj2", "subj3"}


def test_list_qc_subject_ids_empty():
    mock_client = MagicMock()
    mock_client.get_paginator.return_value.paginate.return_value = [
        {"Contents": []}
    ]
    result = list_qc_subject_ids(mock_client)
    assert result == set()


def test_build_platform_table_spim(tmp_path, sample_asset_basics, sample_qc_data):
    qc_path = tmp_path / "qc_subj1.pqt"
    sample_qc_data[sample_qc_data["subject_id"] == "subj1"].to_parquet(qc_path, index=False)

    basics_path = tmp_path / "asset_basics.pqt"
    sample_asset_basics.to_parquet(basics_path, index=False)

    con = duckdb.connect()
    con.execute(f"CREATE TABLE asset_basics AS SELECT * FROM read_parquet('{basics_path}')")

    df = build_platform_table(con, PLATFORMS["spim"], [str(qc_path)])
    con.close()

    assert "asset_name" in df.columns
    assert "subject_id" in df.columns
    assert "instrument_id" in df.columns
    assert "experimenter" in df.columns
    assert "metric_name" in df.columns
    assert "status" in df.columns
    assert "timestamp" in df.columns

    assert set(df["asset_name"].unique()) == {"spim_asset_1", "spim_asset_2"}
    assert df[df["asset_name"] == "spim_asset_1"]["instrument_id"].iloc[0] == "rig_a"

    alice_rows = df[df["experimenter"] == "Alice"]
    assert len(alice_rows) > 0
    bob_rows = df[df["experimenter"] == "Bob"]
    assert len(bob_rows) > 0
    assert alice_rows["asset_name"].iloc[0] == "spim_asset_1"

    statuses = df["status"].unique()
    assert "Pass" in statuses
    assert "Fail" in statuses


def test_build_platform_table_unknown_instrument(tmp_path, sample_asset_basics, sample_qc_data):
    qc_path = tmp_path / "qc_subj2.pqt"
    sample_qc_data[sample_qc_data["subject_id"] == "subj2"].to_parquet(qc_path, index=False)

    basics_path = tmp_path / "asset_basics.pqt"
    sample_asset_basics.to_parquet(basics_path, index=False)

    con = duckdb.connect()
    con.execute(f"CREATE TABLE asset_basics AS SELECT * FROM read_parquet('{basics_path}')")

    df = build_platform_table(con, PLATFORMS["fib"], [str(qc_path)])
    con.close()

    assert df[df["asset_name"] == "fib_asset_1"]["instrument_id"].iloc[0] == "(unknown)"
    assert df[df["asset_name"] == "fib_asset_1"]["experimenter"].iloc[0] == "(unknown)"


def test_build_platform_table_vr(tmp_path, sample_asset_basics):
    qc_vr = pd.DataFrame({
        "name": ["VR Metric"],
        "modality": ["ecephys"],
        "stage": ["Processing"],
        "value": ["good"],
        "status": ["Pass"],
        "asset_name": ["vr_asset_1"],
        "subject_id": ["subj3"],
        "timestamp": pd.to_datetime(["2025-06-04"]),
    })
    qc_path = tmp_path / "qc_subj3.pqt"
    qc_vr.to_parquet(qc_path, index=False)

    con = duckdb.connect()
    basics_path = tmp_path / "asset_basics.pqt"
    sample_asset_basics.to_parquet(basics_path, index=False)
    con.execute(f"CREATE TABLE asset_basics AS SELECT * FROM read_parquet('{basics_path}')")

    df = build_platform_table(con, PLATFORMS["vr"], [str(qc_path)])
    con.close()

    assert len(df) == 1
    assert df.iloc[0]["metric_name"] == "VR Metric"
    assert df.iloc[0]["experimenter"] == "Dave"
    assert df.iloc[0]["instrument_id"] == "rig_c"


def test_upload_parquet():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    mock_client = MagicMock()

    upload_parquet(df, mock_client, "test/output.pqt")

    mock_client.put_object.assert_called_once()
    call_kwargs = mock_client.put_object.call_args[1]
    assert call_kwargs["Bucket"] == S3_BUCKET
    assert call_kwargs["Key"] == "test/output.pqt"

    buf = io.BytesIO(call_kwargs["Body"])
    table = pq.read_table(buf)
    result = table.to_pandas()
    assert list(result.columns) == ["a", "b"]
    assert len(result) == 2
