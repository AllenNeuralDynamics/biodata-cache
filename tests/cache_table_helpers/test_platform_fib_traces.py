"""Unit tests for platform_fib_traces cache table."""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import biodata_cache.cache_table_helpers.platform_fib_traces as fib_traces
from biodata_cache.cache_table_helpers.platform_fib_traces import (
    _FP_GROUP,
    _download_zarr_store,
    _extract_session_traces,
    _fetch_asset_fib_traces,
    _fetch_implanted_fibers,
    _find_nwb_prefix,
    _open_nwb_zarr,
    _parse_s3,
    platform_fib_traces,
    platform_fib_traces_columns,
)


class _FakeSeries:
    def __init__(self, data, timestamps):
        self._d = {"data": np.array(data), "timestamps": np.array(timestamps)}

    def __getitem__(self, key):
        return self._d[key]


class _FakeFP:
    def __init__(self, series):
        self._series = series

    def group_keys(self):
        return list(self._series.keys())

    def __getitem__(self, key):
        return self._series[key]


class _FakeRoot:
    def __init__(self, fp, has_fp=True):
        self._fp = fp
        self._has_fp = has_fp

    def __contains__(self, key):
        return key == _FP_GROUP and self._has_fp

    def __getitem__(self, key):
        return self._fp


def _basics_df():
    return pd.DataFrame(
        {
            "subject_id": ["856239", "856239", "999999"],
            "modalities": [["fib"], ["fib"], ["fib"]],
            "data_level": ["derived", "raw", "derived"],
            "location": ["s3://bucket/abc", "s3://bucket/raw", "s3://bucket/other"],
            "name": ["asset_derived", "asset_raw", "asset_other"],
        }
    )


def test_extract_session_traces_builds_wide_form():
    fp = _FakeFP(
        {
            "G_0_dff-bright": _FakeSeries([1.0, 2.0], [0.1, 0.2]),
            "G_0_dff-exp": _FakeSeries([5.0, 6.0], [0.1, 0.2]),
            "Iso_3_dff-poly_mc-iso-IRLS": _FakeSeries([3.0, 4.0], [0.1, 0.2]),
            "not_a_series": _FakeSeries([9.0], [0.1]),
        }
    )
    root = _FakeRoot(fp)

    df = _extract_session_traces(root, {0, 3})

    assert list(df.columns) == ["fiber", "channel", "timestamp", "dff-bright"]
    assert len(df) == 2
    assert set(df["channel"]) == {"G"}
    assert set(df["fiber"]) == {0}
    assert list(df["dff-bright"].astype(float)) == [1.0, 2.0]


def test_extract_session_traces_drops_fibers_without_implant():
    fp = _FakeFP(
        {
            "G_0_dff-bright": _FakeSeries([1.0, 2.0], [0.1, 0.2]),
            "G_2_dff-bright": _FakeSeries([5.0, 6.0], [0.1, 0.2]),
        }
    )
    df = _extract_session_traces(_FakeRoot(fp), {0})
    assert set(df["fiber"]) == {0}


def test_extract_session_traces_mismatched_lengths_truncates():
    fp = _FakeFP({"R_1_dff-bright": _FakeSeries([1.0, 2.0, 3.0], [0.1, 0.2])})
    df = _extract_session_traces(_FakeRoot(fp), {1})
    assert len(df) == 2
    assert "dff-bright" in df.columns


def test_extract_session_traces_no_fp_group_returns_empty():
    df = _extract_session_traces(_FakeRoot(_FakeFP({}), has_fp=False), {0})
    assert df.empty


def test_extract_session_traces_no_matching_series_returns_empty():
    fp = _FakeFP({"random_group": _FakeSeries([1.0], [0.1])})
    df = _extract_session_traces(_FakeRoot(fp), {0})
    assert df.empty


def test_parse_s3_valid():
    assert _parse_s3("s3://bucket/a/b/") == ("bucket", "a/b")


def test_parse_s3_invalid_raises():
    with pytest.raises(ValueError, match="Not an S3 URI"):
        _parse_s3("/local/path")


def test_find_nwb_prefix_found():
    client = MagicMock()
    client.list_objects_v2.return_value = {
        "CommonPrefixes": [{"Prefix": "k/nwb/other/"}, {"Prefix": "k/nwb/session.nwb/"}]
    }
    assert _find_nwb_prefix(client, "bucket", "k") == "k/nwb/session.nwb"


def test_find_nwb_prefix_not_found():
    client = MagicMock()
    client.list_objects_v2.return_value = {}
    assert _find_nwb_prefix(client, "bucket", "k") is None


def test_download_zarr_store():
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "nwbpfx/processing/fiber_photometry/G_0/data/0"}]},
        {},
    ]
    client.get_paginator.return_value = paginator
    body = MagicMock()
    body.read.return_value = b"bytes"
    client.get_object.return_value = {"Body": body}

    store = _download_zarr_store(client, "bucket", "nwbpfx")

    assert ".zmetadata" in store
    assert "processing/fiber_photometry/G_0/data/0" in store
    assert store[".zmetadata"] == b"bytes"


@patch("biodata_cache.cache_table_helpers.platform_fib_traces._download_zarr_store")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._find_nwb_prefix")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.boto3")
@patch("zarr.open_consolidated")
def test_open_nwb_zarr_found(mock_open, mock_boto3, mock_find, mock_download):
    mock_find.return_value = "k/nwb/session.nwb"
    mock_download.return_value = {".zmetadata": b"{}"}
    mock_open.return_value = "ROOT"

    result = _open_nwb_zarr("s3://bucket/k")

    mock_open.assert_called_once_with({".zmetadata": b"{}"}, mode="r")
    assert result == "ROOT"


@patch("biodata_cache.cache_table_helpers.platform_fib_traces._find_nwb_prefix")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.boto3")
def test_open_nwb_zarr_not_found(mock_boto3, mock_find):
    mock_find.return_value = None
    assert _open_nwb_zarr("s3://bucket/abc") is None


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_implanted_fibers")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._open_nwb_zarr")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._extract_session_traces")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.asset_basics")
def test_fetch_asset_filters_and_writes(mock_basics, mock_extract, mock_open, mock_fibers, mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_basics.return_value = _basics_df()
    mock_fibers.return_value = {0}
    mock_open.return_value = "ROOT"
    mock_extract.return_value = pd.DataFrame(
        {
            "fiber": [0],
            "channel": ["G"],
            "timestamp": [1.0],
            "dff-bright": [1.0],
        }
    )

    result = _fetch_asset_fib_traces("asset_derived")

    mock_open.assert_called_once_with("s3://bucket/abc")
    mock_extract.assert_called_once_with("ROOT", {0})
    mock_registry.BACKEND.write.assert_called_once()
    assert mock_registry.BACKEND.write.call_args[0][0] == "platform_fib_traces/asset_derived"
    assert result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._open_nwb_zarr")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.asset_basics")
def test_fetch_asset_skips_unknown_asset(mock_basics, mock_open, mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_basics.return_value = _basics_df()

    result = _fetch_asset_fib_traces("missing_asset")

    mock_open.assert_not_called()
    assert result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._open_nwb_zarr")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.asset_basics")
def test_fetch_asset_skips_missing_location(mock_basics, mock_open, mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    df = _basics_df()
    df.loc[df["name"] == "asset_derived", "location"] = ""
    mock_basics.return_value = df

    result = _fetch_asset_fib_traces("asset_derived")

    mock_open.assert_not_called()
    assert result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_implanted_fibers")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._open_nwb_zarr")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.asset_basics")
def test_fetch_asset_skips_when_no_implants(mock_basics, mock_open, mock_fibers, mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_basics.return_value = _basics_df()
    mock_fibers.return_value = set()

    result = _fetch_asset_fib_traces("asset_derived")

    mock_open.assert_not_called()
    assert result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_implanted_fibers")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._extract_session_traces")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._open_nwb_zarr")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.asset_basics")
def test_fetch_asset_skips_missing_nwb(mock_basics, mock_open, mock_extract, mock_fibers, mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_basics.return_value = _basics_df()
    mock_fibers.return_value = {0}
    mock_open.return_value = None

    result = _fetch_asset_fib_traces("asset_derived")

    mock_extract.assert_not_called()
    assert result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_implanted_fibers")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._open_nwb_zarr")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces._extract_session_traces")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.asset_basics")
def test_fetch_asset_skips_empty_session(mock_basics, mock_extract, mock_open, mock_fibers, mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_basics.return_value = _basics_df()
    mock_fibers.return_value = {0}
    mock_open.return_value = "ROOT"
    mock_extract.return_value = pd.DataFrame()

    result = _fetch_asset_fib_traces("asset_derived")

    mock_registry.BACKEND.write.assert_not_called()
    assert result.empty


@patch("aind_data_access_api.document_db.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
def test_fetch_implanted_fibers_parses_probe_implants(mock_registry, mock_client_cls):
    mock_registry.API_GATEWAY_HOST = "host"
    mock_client = MagicMock()
    mock_client.retrieve_docdb_records.return_value = [
        {
            "procedures": {
                "subject_procedures": [
                    {
                        "procedures": [
                            {"object_type": "Probe implant", "implanted_device": {"name": "Fiber_0"}},
                            {"object_type": "Probe implant", "implanted_device": {"name": "Fiber 2"}},
                            {"object_type": "Anaesthetic"},
                            {"object_type": "Probe implant", "implanted_device": {"name": "Lens"}},
                        ]
                    }
                ]
            }
        }
    ]
    mock_client_cls.return_value = mock_client

    fibers = _fetch_implanted_fibers("asset_derived")

    assert fibers == {0, 2}


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
def test_platform_fib_traces_reads_from_cache(mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.read.return_value = pd.DataFrame({"value": [1.0]})

    result = platform_fib_traces(asset_name="asset_derived")

    mock_registry.BACKEND.read.assert_called_once_with("platform_fib_traces/asset_derived")
    assert not result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
def test_platform_fib_traces_raises_on_empty_without_force(mock_registry):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.read.return_value = pd.DataFrame()

    with pytest.raises(ValueError, match="Cache is empty"):
        platform_fib_traces(asset_name="asset_derived")


@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_asset_fib_traces")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
def test_platform_fib_traces_force_update_fetches(mock_registry, mock_fetch):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    mock_fetch.return_value = pd.DataFrame({"value": [1.0]})

    result = platform_fib_traces(asset_name="asset_derived", force_update=True)

    mock_fetch.assert_called_once_with("asset_derived")
    assert not result.empty


@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_asset_fib_traces")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
def test_platform_fib_traces_lazy_returns_location(mock_registry, mock_fetch):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.get_location.return_value = "s3://loc/data.pqt"

    result = platform_fib_traces(asset_name="asset_derived", lazy=True)

    mock_fetch.assert_not_called()
    mock_registry.BACKEND.get_location.assert_called_once_with("platform_fib_traces/asset_derived")
    assert result == "s3://loc/data.pqt"


@patch("biodata_cache.cache_table_helpers.platform_fib_traces._fetch_asset_fib_traces")
@patch("biodata_cache.cache_table_helpers.platform_fib_traces.registry")
def test_platform_fib_traces_lazy_force_update_fetches(mock_registry, mock_fetch):
    mock_registry.NAMES = {"fib_traces": "platform_fib_traces"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.get_location.return_value = "s3://loc/data.pqt"

    result = platform_fib_traces(asset_name="asset_derived", lazy=True, force_update=True)

    mock_fetch.assert_called_once_with("asset_derived")
    assert result == "s3://loc/data.pqt"


def test_platform_fib_traces_columns():
    cols = platform_fib_traces_columns()
    names = [c.name for c in cols]
    assert names == ["fiber", "channel", "timestamp", "dff-bright"]


def test_log_emits(caplog):
    with patch.object(fib_traces.registry, "BACKEND", MagicMock()):
        with caplog.at_level("INFO"):
            fib_traces._log("hello")
    assert "hello" in caplog.text
