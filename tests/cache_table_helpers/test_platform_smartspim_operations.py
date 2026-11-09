"""Unit tests for platform_smartspim_operations cache table wiring."""

import json
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


def test_registers_log_schema():
    schema = smartspim_ops.cw.schema_for("SmartSPIM Pipeline")
    assert schema.asset_field == "dataset_name"
    assert schema.error_field == "error"
    assert {"pipeline_plan", "stage_failure", "pipeline_finished"} <= set(schema.event_types)


def test_query_uses_dataset_name_and_excludes_legacy_rows():
    q = smartspim_ops.cw.query_string("SmartSPIM Pipeline")
    assert 'dataset_name != ""' in q
    assert "acquisition_name" not in q
    assert "dataset_name not like /^Ex_/" in q
    assert "dataset_name not like /_stitched_/" in q
    assert '"stage_failure"' in q


def test_parse_row_reads_dataset_name_and_error():
    record = {
        "timestamp": "2026-07-27T10:00:00+00:00",
        "level": "ERROR",
        "message": "failed",
        "dataset_name": "SmartSPIM_123_2026-01-01_00-00-00",
        "process_name": "stitch",
        "event_type": "stage_failure",
        "pipeline_name": "SmartSPIM Pipeline",
        "error": "boom",
    }
    row = [
        {"field": "@timestamp", "value": "2026-07-27 10:00:00.000"},
        {"field": "@message", "value": json.dumps(record)},
        {"field": "@logStream", "value": "stream"},
    ]
    parsed = smartspim_ops.cw.parse_row(row)
    assert parsed["asset_name"] == "SmartSPIM_123_2026-01-01_00-00-00"
    assert parsed["error_info"] == "boom"
    assert parsed["event_type"] == "stage_error"


def test_run_level_events_pass_through():
    schema = smartspim_ops.cw.schema_for("SmartSPIM Pipeline")
    assert schema.normalize_event_type("pipeline_finished") == "pipeline_finished"
    assert schema.normalize_event_type("pipeline_plan") == "pipeline_plan"
    assert schema.normalize_event_type("stage_complete") == "stage_complete"


def test_columns_names():
    names = {c.name for c in platform_smartspim_operations_columns()}
    assert {"timestamp", "ingest_ts", "process_name", "event_type", "error_info", "cloudwatch_url"} <= names
