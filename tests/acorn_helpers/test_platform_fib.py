"""Unit tests for platform_fib acorn."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from zombie_squirrel.acorn_helpers.platform_fib import (
    _build_fib_rows,
    _extract_fiber_channel_map,
    _extract_fiber_structure_map,
    _fetch_fib_records,
    platform_fib,
    platform_fib_columns,
)

EXAMPLE_RECORD = {
    "_id": "abc123",
    "name": "behavior_854147_2026-05-18_13-14-35",
    "procedures": {
        "subject_procedures": [
            {
                "object_type": "Surgery",
                "procedures": [
                    {
                        "object_type": "Probe implant",
                        "implanted_device": {"object_type": "Fiber probe", "name": "Fiber_0"},
                        "device_config": {
                            "primary_targeted_structure": {
                                "atlas": "CCFv3",
                                "name": "Nucleus accumbens",
                                "acronym": "ACB",
                                "id": "56",
                            }
                        },
                    },
                    {
                        "object_type": "Probe implant",
                        "implanted_device": {"object_type": "Fiber probe", "name": "Fiber_1"},
                        "device_config": {
                            "primary_targeted_structure": {
                                "atlas": "CCFv3",
                                "name": "Piriform area",
                                "acronym": "PIR",
                                "id": "215",
                            }
                        },
                    },
                ],
            }
        ]
    },
    "acquisition": {
        "data_streams": [
            {
                "configurations": [
                    {
                        "object_type": "Patch cord config",
                        "device_name": "Patch Cord A",
                        "channels": [
                            {
                                "channel_name": "Fiber 0_green",
                                "intended_measurement": "DA",
                            }
                        ],
                    },
                    {
                        "object_type": "Patch cord config",
                        "device_name": "Patch Cord B",
                        "channels": [
                            {
                                "channel_name": "Fiber 1_green",
                                "intended_measurement": "5-HT",
                            }
                        ],
                    },
                ]
            }
        ]
    },
}


class TestExtractFiberStructureMap(unittest.TestCase):
    """Tests for _extract_fiber_structure_map."""

    def test_extracts_fiber_structure(self):
        """Test fiber structure acronyms extracted from probe implant procedures."""
        result = _extract_fiber_structure_map(EXAMPLE_RECORD)
        self.assertEqual(result, {"Fiber_0": "ACB", "Fiber_1": "PIR"})

    def test_empty_procedures(self):
        """Test returns empty dict when no procedures present."""
        result = _extract_fiber_structure_map({})
        self.assertEqual(result, {})

    def test_skips_non_probe_implant(self):
        """Test non-probe-implant procedures are ignored."""
        record = {
            "procedures": {
                "subject_procedures": [
                    {
                        "procedures": [
                            {"object_type": "Headframe"},
                        ]
                    }
                ]
            }
        }
        result = _extract_fiber_structure_map(record)
        self.assertEqual(result, {})

    def test_none_targeted_structure(self):
        """Test fiber with no targeted structure returns None acronym."""
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
        result = _extract_fiber_structure_map(record)
        self.assertEqual(result, {"Fiber_0": None})


class TestExtractFiberChannelMap(unittest.TestCase):
    """Tests for _extract_fiber_channel_map."""

    def test_extracts_intended_measurement(self):
        """Test intended measurement extracted from patch cord configs."""
        result = _extract_fiber_channel_map(EXAMPLE_RECORD)
        self.assertEqual(result, {"Fiber 0": "DA", "Fiber 1": "5-HT"})

    def test_empty_acquisition(self):
        """Test returns empty dict when no acquisition present."""
        result = _extract_fiber_channel_map({})
        self.assertEqual(result, {})

    def test_skips_non_patch_cord_configs(self):
        """Test non-patch-cord configurations are ignored."""
        record = {
            "acquisition": {
                "data_streams": [
                    {
                        "configurations": [
                            {"object_type": "Detector config", "device_name": "camera"},
                        ]
                    }
                ]
            }
        }
        result = _extract_fiber_channel_map(record)
        self.assertEqual(result, {})

    def test_null_intended_measurement(self):
        """Test null intended_measurement is stored as None."""
        record = {
            "acquisition": {
                "data_streams": [
                    {
                        "configurations": [
                            {
                                "object_type": "Patch cord config",
                                "device_name": "Patch Cord A",
                                "channels": [
                                    {"channel_name": "Fiber 0_green", "intended_measurement": None}
                                ],
                            }
                        ]
                    }
                ]
            }
        }
        result = _extract_fiber_channel_map(record)
        self.assertIsNone(result["Fiber 0"])


class TestBuildFibRows(unittest.TestCase):
    """Tests for _build_fib_rows."""

    def test_builds_one_row_per_fiber(self):
        """Test one row produced per (asset, fiber) pair."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        self.assertEqual(len(rows), 2)

    def test_row_columns(self):
        """Test row contains expected columns."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        row0 = rows[0]
        self.assertIn("asset_name", row0)
        self.assertIn("fiber_name", row0)
        self.assertIn("targeted_structure", row0)
        self.assertIn("intended_measurement", row0)

    def test_row_values(self):
        """Test row values are correctly extracted and cross-referenced."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        by_fiber = {r["fiber_name"]: r for r in rows}
        self.assertEqual(by_fiber["Fiber_0"]["targeted_structure"], "ACB")
        self.assertEqual(by_fiber["Fiber_0"]["intended_measurement"], "DA")
        self.assertEqual(by_fiber["Fiber_1"]["targeted_structure"], "PIR")
        self.assertEqual(by_fiber["Fiber_1"]["intended_measurement"], "5-HT")

    def test_asset_name_set(self):
        """Test asset_name is set from record name."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        for row in rows:
            self.assertEqual(row["asset_name"], "behavior_854147_2026-05-18_13-14-35")

    def test_empty_records(self):
        """Test empty records list returns empty rows list."""
        rows = _build_fib_rows([])
        self.assertEqual(rows, [])

    def test_channel_not_matched_returns_none(self):
        """Test intended_measurement is None when no channel matches fiber."""
        record = {
            "name": "asset_x",
            "procedures": {
                "subject_procedures": [
                    {
                        "procedures": [
                            {
                                "object_type": "Probe implant",
                                "implanted_device": {"name": "Fiber_5"},
                                "device_config": {
                                    "primary_targeted_structure": {"acronym": "MOp"}
                                },
                            }
                        ]
                    }
                ]
            },
            "acquisition": {"data_streams": []},
        }
        rows = _build_fib_rows([record])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["intended_measurement"])


class TestFetchFibRecords(unittest.TestCase):
    """Tests for _fetch_fib_records."""

    @patch("zombie_squirrel.acorn_helpers.platform_fib.MetadataDbClient")
    def test_fetches_in_batches(self, mock_client_class):
        """Test batching logic sends multiple requests for >100 assets."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.retrieve_docdb_records.return_value = []

        names = [f"asset_{i}" for i in range(250)]
        _fetch_fib_records(names)

        self.assertEqual(mock_client.retrieve_docdb_records.call_count, 3)

    @patch("zombie_squirrel.acorn_helpers.platform_fib.MetadataDbClient")
    def test_returns_all_records(self, mock_client_class):
        """Test records from all batches are combined."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.retrieve_docdb_records.side_effect = [
            [{"name": "asset_0"}],
            [{"name": "asset_100"}],
        ]

        names = [f"asset_{i}" for i in range(150)]
        result = _fetch_fib_records(names)

        self.assertEqual(len(result), 2)


class TestPlatformFib(unittest.TestCase):
    """Tests for platform_fib acorn function."""

    @patch("zombie_squirrel.acorn_helpers.platform_fib.acorns.TREE")
    def test_cache_hit(self, mock_tree):
        """Test returning cached DataFrame when cache is populated."""
        cached_df = pd.DataFrame(
            {
                "asset_name": ["behavior_123"],
                "fiber_name": ["Fiber_0"],
                "targeted_structure": ["ACB"],
                "intended_measurement": ["DA"],
            }
        )
        mock_tree.scurry.return_value = cached_df

        result = platform_fib(force_update=False)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["targeted_structure"], "ACB")

    @patch("zombie_squirrel.acorn_helpers.platform_fib.acorns.TREE")
    def test_empty_cache_raises_error(self, mock_tree):
        """Test empty cache raises ValueError without force_update."""
        mock_tree.scurry.return_value = pd.DataFrame()

        with self.assertRaises(ValueError) as ctx:
            platform_fib(force_update=False)

        self.assertIn("Cache is empty", str(ctx.exception))
        self.assertIn("force_update=True", str(ctx.exception))

    @patch("zombie_squirrel.acorn_helpers.platform_fib.MetadataDbClient")
    @patch("zombie_squirrel.acorn_helpers.platform_fib.asset_basics")
    @patch("zombie_squirrel.acorn_helpers.platform_fib.acorns.TREE")
    def test_force_update_fetches_and_caches(self, mock_tree, mock_basics, mock_client_class):
        """Test force_update fetches from DB and stores result in cache."""
        mock_tree.scurry.return_value = pd.DataFrame()
        mock_basics.return_value = pd.DataFrame(
            {
                "name": ["behavior_854147_2026-05-18_13-14-35"],
                "modalities": ["fib, behavior"],
            }
        )
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.retrieve_docdb_records.return_value = [EXAMPLE_RECORD]

        result = platform_fib(force_update=True)

        self.assertEqual(len(result), 2)
        mock_tree.hide.assert_called_once()

    @patch("zombie_squirrel.acorn_helpers.platform_fib.MetadataDbClient")
    @patch("zombie_squirrel.acorn_helpers.platform_fib.asset_basics")
    @patch("zombie_squirrel.acorn_helpers.platform_fib.acorns.TREE")
    def test_filters_to_fib_modality(self, mock_tree, mock_basics, mock_client_class):
        """Test only assets with 'fib' modality are fetched."""
        mock_tree.scurry.return_value = pd.DataFrame()
        mock_basics.return_value = pd.DataFrame(
            {
                "name": ["fib_asset", "spim_asset", "behavior_asset"],
                "modalities": ["fib, behavior", "SPIM", "behavior"],
            }
        )
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.retrieve_docdb_records.return_value = []

        platform_fib(force_update=True)

        call_args = mock_client.retrieve_docdb_records.call_args
        if call_args:
            names_filter = call_args[1]["filter_query"]["name"]["$in"]
            self.assertIn("fib_asset", names_filter)
            self.assertNotIn("spim_asset", names_filter)
            self.assertNotIn("behavior_asset", names_filter)


class TestPlatformFibColumns(unittest.TestCase):
    """Tests for platform_fib_columns."""

    def test_returns_four_columns(self):
        """Test column list has expected length."""
        cols = platform_fib_columns()
        self.assertEqual(len(cols), 4)

    def test_column_names(self):
        """Test column names match expected output schema."""
        cols = platform_fib_columns()
        names = [c.name for c in cols]
        self.assertIn("asset_name", names)
        self.assertIn("fiber_name", names)
        self.assertIn("targeted_structure", names)
        self.assertIn("intended_measurement", names)


if __name__ == "__main__":
    unittest.main()
