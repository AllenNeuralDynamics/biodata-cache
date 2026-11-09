"""Unit tests for platform_smartspim_operations cache table wiring."""

from unittest.mock import patch

import pandas as pd

import biodata_cache.cache_table_helpers.platform_smartspim_operations as smartspim_ops
from biodata_cache.cache_table_helpers.platform_smartspim_operations import (
    fetch_all_smartspim_operations,
    platform_smartspim_operations,
    platform_smartspim_operations_columns,
)


def test_fetch_all_delegates_to_shared():
    with patch.object(smartspim_ops.cw, "fetch_all_operations", return_value=["a"]) as fetch_all:
        assert fetch_all_smartspim_operations() == ["a"]
    fetch_all.assert_called_once_with(
        "smartspim_operations", smartspim_ops._PIPELINE_NAME, smartspim_ops.cw.DEFAULT_LOOKBACK_DAYS
    )


def test_platform_smartspim_operations_delegates_to_shared():
    df = pd.DataFrame({"event_type": ["stage_start"]})
    with patch.object(smartspim_ops.cw, "platform_operations", return_value=df) as op:
        out = platform_smartspim_operations("acq1", force_update=True, lazy=False)
    op.assert_called_once_with("smartspim_operations", smartspim_ops._PIPELINE_NAME, "acq1", True, False)
    pd.testing.assert_frame_equal(out, df)


def test_registers_pipeline():
    assert smartspim_ops.cw._OPERATIONS_PIPELINES.get("SmartSPIM Pipeline") == "smartspim_operations"


def test_pipeline_name():
    assert smartspim_ops._PIPELINE_NAME == "SmartSPIM Pipeline"


def test_columns_names():
    names = {c.name for c in platform_smartspim_operations_columns()}
    assert {"timestamp", "ingest_ts", "process_name", "event_type", "error_info", "cloudwatch_url"} <= names
