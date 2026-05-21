"""Unit tests for platform_fib acorn."""

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from zombie_squirrel.acorn_helpers.platform_fib import (
    MAX_FIBERS,
    _build_fib_rows,
    _extract_fiber_channel_map,
    _extract_fiber_structure_map,
    _fetch_fib_records,
    _fiber_sort_key,
    _lookup_channel,
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


class TestFiberSortKey(unittest.TestCase):
    """Tests for _fiber_sort_key."""

    def test_extracts_trailing_integer(self):
        """Test trailing integer extracted from fiber name."""
        self.assertEqual(_fiber_sort_key("Fiber_0"), 0)
        self.assertEqual(_fiber_sort_key("Fiber_3"), 3)
        self.assertEqual(_fiber_sort_key("Fiber_12"), 12)

    def test_no_integer_returns_zero(self):
        """Test returns 0 when no integer in name."""
        self.assertEqual(_fiber_sort_key("Fiber"), 0)


class TestLookupChannel(unittest.TestCase):
    """Tests for _lookup_channel."""

    def test_exact_match(self):
        """Test exact key match returns value."""
        self.assertEqual(_lookup_channel("Fiber_0", {"Fiber_0": "DA"}), "DA")

    def test_space_variant_fallback(self):
        """Test underscore-to-space normalization finds key."""
        self.assertEqual(_lookup_channel("Fiber_0", {"Fiber 0": "DA"}), "DA")

    def test_missing_returns_none(self):
        """Test missing key returns None."""
        self.assertIsNone(_lookup_channel("Fiber_5", {"Fiber 0": "DA"}))


class TestBuildFibRows(unittest.TestCase):
    """Tests for _build_fib_rows."""

    def test_builds_one_row_per_asset(self):
        """Test one row produced per asset, not per fiber."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        self.assertEqual(len(rows), 1)

    def test_row_has_asset_name(self):
        """Test row contains asset_name."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        self.assertEqual(rows[0]["asset_name"], "behavior_854147_2026-05-18_13-14-35")

    def test_row_has_fiber_columns(self):
        """Test row has fiber_N_targeted_structure and fiber_N_intended_measurement for each fiber slot."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        row = rows[0]
        for i in range(MAX_FIBERS):
            self.assertIn(f"fiber_{i}_targeted_structure", row)
            self.assertIn(f"fiber_{i}_intended_measurement", row)

    def test_fiber_values_correct(self):
        """Test fiber columns populated correctly from procedures and acquisition."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        row = rows[0]
        self.assertEqual(row["fiber_0_targeted_structure"], "ACB")
        self.assertEqual(row["fiber_0_intended_measurement"], "DA")
        self.assertEqual(row["fiber_1_targeted_structure"], "PIR")
        self.assertEqual(row["fiber_1_intended_measurement"], "5-HT")

    def test_unused_fiber_slots_are_none(self):
        """Test fiber columns beyond available fibers are None."""
        rows = _build_fib_rows([EXAMPLE_RECORD])
        row = rows[0]
        # EXAMPLE_RECORD has 2 fibers; slots 2 and 3 should be None
        self.assertIsNone(row["fiber_2_targeted_structure"])
        self.assertIsNone(row["fiber_2_intended_measurement"])
        self.assertIsNone(row["fiber_3_targeted_structure"])
        self.assertIsNone(row["fiber_3_intended_measurement"])

    def test_empty_records(self):
        """Test empty records list returns empty rows list."""
        rows = _build_fib_rows([])
        self.assertEqual(rows, [])

    def test_multiple_assets_produce_multiple_rows(self):
        """Test two assets produce two rows."""
        record2 = {**EXAMPLE_RECORD, "name": "behavior_999_2026-01-01"}
        rows = _build_fib_rows([EXAMPLE_RECORD, record2])
        self.assertEqual(len(rows), 2)

    def test_fibers_sorted_by_index(self):
        """Test fibers are ordered by their trailing integer regardless of insertion order."""
        record = {
            "name": "asset_x",
            "procedures": {
                "subject_procedures": [
                    {
                        "procedures": [
                            {
                                "object_type": "Probe implant",
                                "implanted_device": {"name": "Fiber_1"},
                                "device_config": {"primary_targeted_structure": {"acronym": "PIR"}},
                            },
                            {
                                "object_type": "Probe implant",
                                "implanted_device": {"name": "Fiber_0"},
                                "device_config": {"primary_targeted_structure": {"acronym": "ACB"}},
                            },
                        ]
                    }
                ]
            },
            "acquisition": {"data_streams": []},
        }
        rows = _build_fib_rows([record])
        row = rows[0]
        self.assertEqual(row["fiber_0_targeted_structure"], "ACB")
        self.assertEqual(row["fiber_1_targeted_structure"], "PIR")


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
                "fiber_0_targeted_structure": ["ACB"],
                "fiber_0_intended_measurement": ["DA"],
            }
        )
        mock_tree.scurry.return_value = cached_df

        result = platform_fib(force_update=False)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["fiber_0_targeted_structure"], "ACB")

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

        # one row per asset
        self.assertEqual(len(result), 1)
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

    def test_returns_correct_count(self):
        """Test column list has one asset_name plus two columns per fiber slot."""
        cols = platform_fib_columns()
        self.assertEqual(len(cols), 1 + MAX_FIBERS * 2)

    def test_column_names(self):
        """Test column names match expected output schema."""
        cols = platform_fib_columns()
        names = [c.name for c in cols]
        self.assertIn("asset_name", names)
        for i in range(MAX_FIBERS):
            self.assertIn(f"fiber_{i}_targeted_structure", names)
            self.assertIn(f"fiber_{i}_intended_measurement", names)


if __name__ == "__main__":
    unittest.main()
