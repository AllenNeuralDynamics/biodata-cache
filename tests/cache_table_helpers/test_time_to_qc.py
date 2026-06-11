"""Unit tests for time_to_qc cache table."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers.time_to_qc import (
    _get_last_metric_timestamp,
    _get_last_process_datetime,
    _get_qc_time,
    _has_pending_status,
    time_to_qc,
)


@pytest.fixture(autouse=True)
def reset_backend():
    registry.BACKEND = MemoryBackend()


# --- _get_last_process_datetime ---


def test_get_last_process_datetime_empty():
    assert _get_last_process_datetime({}) is None


def test_get_last_process_datetime_none_list():
    assert _get_last_process_datetime({"data_processes": None}) is None


def test_get_last_process_datetime_empty_list():
    assert _get_last_process_datetime({"data_processes": []}) is None


def test_get_last_process_datetime_end_date_time():
    processing = {
        "data_processes": [
            {"end_date_time": "2025-04-01T10:00:00", "start_date_time": "2025-04-01T08:00:00"},
            {"end_date_time": "2025-04-22T20:50:47", "start_date_time": "2025-04-22T18:00:00"},
        ]
    }
    assert _get_last_process_datetime(processing) == "2025-04-22T20:50:47"


def test_get_last_process_datetime_falls_back_to_start():
    processing = {
        "data_processes": [
            {"start_date_time": "2025-04-22T18:00:00"},
        ]
    }
    assert _get_last_process_datetime(processing) == "2025-04-22T18:00:00"


def test_get_last_process_datetime_returns_last_not_first():
    processing = {
        "data_processes": [
            {"end_date_time": "2025-03-01T00:00:00"},
            {"end_date_time": "2025-04-22T20:50:47"},
        ]
    }
    assert _get_last_process_datetime(processing) == "2025-04-22T20:50:47"


# --- _has_pending_status ---


def test_has_pending_status_true():
    status = {"pophys": "Pending", "Processing": "Pass"}
    assert _has_pending_status(status) is True


def test_has_pending_status_all_pending():
    status = {"pophys": "Pending", "Processing": "Pending"}
    assert _has_pending_status(status) is True


def test_has_pending_status_false():
    status = {"pophys": "Pass", "Processing": "Pass"}
    assert _has_pending_status(status) is False


def test_has_pending_status_empty():
    assert _has_pending_status({}) is False


# --- _get_last_metric_timestamp ---


def test_get_last_metric_timestamp_single_metric():
    metrics = [
        {"status_history": [{"status": "Pass", "timestamp": "2025-04-23T00:38:48+00:00"}]}
    ]
    assert _get_last_metric_timestamp(metrics) == "2025-04-23T00:38:48+00:00"


def test_get_last_metric_timestamp_returns_latest():
    metrics = [
        {"status_history": [{"status": "Pass", "timestamp": "2025-04-23T00:38:48+00:00"}]},
        {"status_history": [{"status": "Pass", "timestamp": "2025-04-25T12:00:00+00:00"}]},
    ]
    assert _get_last_metric_timestamp(metrics) == "2025-04-25T12:00:00+00:00"


def test_get_last_metric_timestamp_takes_last_history_entry():
    metrics = [
        {
            "status_history": [
                {"status": "Pending", "timestamp": "2025-04-01T00:00:00+00:00"},
                {"status": "Pass", "timestamp": "2025-04-23T00:38:48+00:00"},
            ]
        }
    ]
    assert _get_last_metric_timestamp(metrics) == "2025-04-23T00:38:48+00:00"


def test_get_last_metric_timestamp_empty_metrics():
    assert _get_last_metric_timestamp([]) is None


def test_get_last_metric_timestamp_missing_timestamp():
    metrics = [{"status_history": [{"status": "Pass"}]}]
    assert _get_last_metric_timestamp(metrics) is None


def test_get_last_metric_timestamp_empty_history():
    metrics = [{"status_history": []}]
    assert _get_last_metric_timestamp(metrics) is None


# --- _get_qc_time ---


@patch("biodata_cache.cache_table_helpers.time_to_qc.datetime")
def test_get_qc_time_pending_returns_now(mock_datetime):
    mock_datetime.now.return_value.isoformat.return_value = "2026-06-11T00:00:00+00:00"
    qc = {
        "status": {"pophys": "Pending", "Processing": "Pending"},
        "metrics": [],
    }
    result = _get_qc_time(qc)
    assert result == "2026-06-11T00:00:00+00:00"


def test_get_qc_time_not_pending_returns_metric_timestamp():
    qc = {
        "status": {"pophys": "Pass", "Processing": "Pass"},
        "metrics": [
            {"status_history": [{"status": "Pass", "timestamp": "2025-04-25T12:00:00+00:00"}]},
        ],
    }
    result = _get_qc_time(qc)
    assert result == "2025-04-25T12:00:00+00:00"


def test_get_qc_time_empty_status_returns_metric_timestamp():
    qc = {
        "status": {},
        "metrics": [
            {"status_history": [{"status": "Pass", "timestamp": "2025-04-23T00:38:48+00:00"}]},
        ],
    }
    result = _get_qc_time(qc)
    assert result == "2025-04-23T00:38:48+00:00"


def test_get_qc_time_no_metrics_returns_none():
    qc = {"status": {"pophys": "Pass"}, "metrics": []}
    assert _get_qc_time(qc) is None


# --- time_to_qc main function ---


def test_time_to_qc_cache_hit():
    cached_df = pd.DataFrame(
        {
            "name": ["asset_a"],
            "process_end_time": ["2025-04-22T20:50:47"],
            "qc_time": ["2025-04-23T00:38:48+00:00"],
        }
    )
    registry.BACKEND.write("time_to_qc", cached_df)
    df = time_to_qc(force_update=False)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "asset_a"


def test_time_to_qc_empty_cache_returns_empty():
    df = time_to_qc(force_update=False)
    assert df.empty


@patch("biodata_cache.cache_table_helpers.time_to_qc.asset_basics")
@patch("biodata_cache.cache_table_helpers.time_to_qc.MetadataDbClient")
def test_time_to_qc_force_update_drops_no_qc(mock_client_class, mock_asset_basics):
    mock_asset_basics.return_value = pd.DataFrame(
        {
            "name": ["asset_a", "asset_b"],
            "data_level": ["derived", "derived"],
        }
    )
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [
        {"name": "asset_a", "processing": {"data_processes": []}, "quality_control": None},
        {
            "name": "asset_b",
            "processing": {
                "data_processes": [{"end_date_time": "2025-04-22T20:50:47"}]
            },
            "quality_control": {
                "status": {"pophys": "Pass"},
                "metrics": [
                    {
                        "status_history": [
                            {"status": "Pass", "timestamp": "2025-04-23T00:38:48+00:00"}
                        ]
                    }
                ],
            },
        },
    ]
    df = time_to_qc(force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "asset_b"
    assert df.iloc[0]["process_end_time"] == "2025-04-22T20:50:47"
    assert df.iloc[0]["qc_time"] == "2025-04-23T00:38:48+00:00"


@patch("biodata_cache.cache_table_helpers.time_to_qc.datetime")
@patch("biodata_cache.cache_table_helpers.time_to_qc.asset_basics")
@patch("biodata_cache.cache_table_helpers.time_to_qc.MetadataDbClient")
def test_time_to_qc_pending_qc_uses_now(mock_client_class, mock_asset_basics, mock_datetime):
    mock_datetime.now.return_value.isoformat.return_value = "2026-06-11T00:00:00+00:00"
    mock_asset_basics.return_value = pd.DataFrame(
        {"name": ["asset_c"], "data_level": ["derived"]}
    )
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [
        {
            "name": "asset_c",
            "processing": {"data_processes": []},
            "quality_control": {
                "status": {"pophys": "Pending"},
                "metrics": [
                    {
                        "status_history": [
                            {"status": "Pending", "timestamp": "2025-04-23T00:38:48+00:00"}
                        ]
                    }
                ],
            },
        }
    ]
    df = time_to_qc(force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["qc_time"] == "2026-06-11T00:00:00+00:00"
    assert df.iloc[0]["process_end_time"] is None


@patch("biodata_cache.cache_table_helpers.time_to_qc.asset_basics")
@patch("biodata_cache.cache_table_helpers.time_to_qc.MetadataDbClient")
def test_time_to_qc_no_derived_assets(mock_client_class, mock_asset_basics):
    mock_asset_basics.return_value = pd.DataFrame(
        {"name": ["asset_raw"], "data_level": ["raw"]}
    )
    df = time_to_qc(force_update=True)
    assert df.empty
    mock_client_class.assert_not_called()


@patch("biodata_cache.cache_table_helpers.time_to_qc.asset_basics")
@patch("biodata_cache.cache_table_helpers.time_to_qc.MetadataDbClient")
def test_time_to_qc_cached_after_fetch(mock_client_class, mock_asset_basics):
    mock_asset_basics.return_value = pd.DataFrame(
        {"name": ["asset_d"], "data_level": ["derived"]}
    )
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.retrieve_docdb_records.return_value = [
        {
            "name": "asset_d",
            "processing": {"data_processes": [{"end_date_time": "2025-04-22T20:50:47"}]},
            "quality_control": {
                "status": {"pophys": "Pass"},
                "metrics": [
                    {"status_history": [{"status": "Pass", "timestamp": "2025-04-23T00:38:48+00:00"}]}
                ],
            },
        }
    ]
    time_to_qc(force_update=True)
    df = time_to_qc(force_update=False)
    assert len(df) == 1
    mock_client_class.assert_called_once()
