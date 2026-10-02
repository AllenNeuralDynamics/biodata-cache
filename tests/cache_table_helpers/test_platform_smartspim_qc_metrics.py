"""Tests for the SmartSPIM QC metrics cache table."""

from biodata_cache.cache_table_helpers.platform_smartspim_qc_metrics import (
    _build_rows,
    platform_smartspim_qc_metrics_columns,
)


def test_rows_keep_value_and_omit_redundant_json_columns():
    record = {
        "name": "asset-1",
        "subject": {"subject_id": "subject-1"},
        "data_description": {"data_level": "derived"},
        "instrument": {"instrument_id": "SmartSPIM-1"},
        "acquisition": {"channels": [{"channel_name": "488"}]},
        "quality_control": {
            "metrics": [
                {
                    "name": "Image and tissue quality",
                    "stage": "Processing",
                    "value": {"value": 0.75, "units": "fraction"},
                    "reference": "reference-url",
                    "tags": {"suite": "example"},
                    "status_history": [{"status": "Pass", "evaluator": "Automated", "timestamp": "2026-01-01"}],
                },
                {
                    "name": "488 brightness",
                    "value": 12.5,
                    "status_history": [],
                },
            ]
        },
    }

    rows = _build_rows([record])

    assert [row["value"] for row in rows] == [0.75, 12.5]
    expected_columns = [
        "subject_id",
        "name",
        "metric_name",
        "channel",
        "stage",
        "value",
        "status",
        "evaluator",
        "status_timestamp",
    ]
    assert list(rows[0]) == expected_columns
    assert [column.name for column in platform_smartspim_qc_metrics_columns()] == expected_columns
