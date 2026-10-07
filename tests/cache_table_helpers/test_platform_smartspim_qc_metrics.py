"""Tests for the SmartSPIM QC metrics cache table."""

import unittest

from biodata_cache.cache_table_helpers.platform_smartspim_qc_metrics import (
    _build_rows,
    platform_smartspim_qc_metrics_columns,
)


class PlatformSmartspimQcMetricsTests(unittest.TestCase):
    def test_rows_keep_value_and_omit_redundant_json_columns(self):
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

        self.assertEqual([row["value"] for row in rows], [0.75, 12.5])
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
        self.assertEqual(list(rows[0]), expected_columns)
        self.assertEqual(
            [column.name for column in platform_smartspim_qc_metrics_columns()],
            expected_columns,
        )

    def test_build_rows_uses_channel_tags_without_acquisition_channels(self):
        brightness_metrics = [
            {
                "name": "Ex_488_Em_525 brightness",
                "tags": {"type": "image quality", "channel": "Ex_488_Em_525"},
            },
            {
                "name": "Ex_561_Em_593 brightness",
                "tags": {"type": "image quality", "channel": "Ex_561_Em_593"},
            },
            {
                "name": "Ex_639_Em_660 brightness",
                "tags": {"type": "image quality", "Channel": "Ex_639_Em_660"},
            },
        ]
        record = {
            "name": "SmartSPIM_677289_2023-07-28_12-35-35_stitched_2026-02-28_12-21-18",
            "subject": {"subject_id": "677289"},
            "data_description": {"data_level": "derived"},
            "instrument": {"instrument_id": "SmartSPIM1-2"},
            "acquisition": {},
            "quality_control": {
                "metrics": [
                    {"name": "Image and tissue quality", "tags": {"type": "image quality"}},
                    *brightness_metrics,
                    {"name": "Dataset neuroglancer link", "tags": {"type": "link evaluation"}},
                ]
            },
        }

        rows = _build_rows([record])

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {row["metric_name"]: row["channel"] for row in rows if row["metric_name"].endswith(" brightness")},
            {
                "Ex_488_Em_525 brightness": "Ex_488_Em_525",
                "Ex_561_Em_593 brightness": "Ex_561_Em_593",
                "Ex_639_Em_660 brightness": "Ex_639_Em_660",
            },
        )


if __name__ == "__main__":
    unittest.main()
