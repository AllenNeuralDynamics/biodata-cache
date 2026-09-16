import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from biodata_cache.cache_table_helpers.metadata_core import metadata_core


class TestMetadataCore(unittest.TestCase):
    @patch("aind_data_access_api.document_db.MetadataDbClient")
    @patch("biodata_cache.cache_table_helpers.metadata_core.registry.BACKEND")
    def test_incremental_update_reduces_batches_and_keeps_unchanged_rows(self, mock_backend, mock_client_class):
        mock_backend.read.return_value = pd.DataFrame(
            [
                {"_id": "id1", "_last_modified": "same", "subject": True},
                {"_id": "id2", "_last_modified": "old", "subject": False},
            ]
        )
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.retrieve_docdb_records.side_effect = [
            [
                {"_id": "id1", "_last_modified": "same"},
                {"_id": "id2", "_last_modified": "new"},
                {"_id": "id3", "_last_modified": "new"},
            ],
            [
                {"_id": "id2", "_last_modified": "new", "subject": {}, "processing": None},
                {"_id": "id3", "_last_modified": "new", "acquisition": {}},
            ],
        ]

        result = metadata_core()

        self.assertEqual(set(result["_id"]), {"id1", "id2", "id3"})
        self.assertTrue(result.loc[result["_id"] == "id1", "subject"].iloc[0])
        self.assertTrue(result.loc[result["_id"] == "id2", "subject"].iloc[0])
        self.assertFalse(result.loc[result["_id"] == "id3", "subject"].iloc[0])
        stored = mock_backend.write.call_args.args[1]
        self.assertEqual(
            list(stored.columns),
            [
                "_id",
                "_last_modified",
                "subject",
                "data_description",
                "procedures",
                "instrument",
                "acquisition",
                "processing",
                "quality_control",
            ],
        )
        self.assertEqual(mock_client.retrieve_docdb_records.call_count, 2)
        mock_client.aggregate_docdb_records.assert_not_called()
        self.assertEqual(
            mock_client.retrieve_docdb_records.call_args_list[1].kwargs["filter_query"],
            {"_id": {"$in": ["id2", "id3"]}},
        )

    @patch("aind_data_access_api.document_db.MetadataDbClient")
    @patch("biodata_cache.cache_table_helpers.metadata_core.registry.BACKEND")
    def test_force_update_replaces_cache(self, mock_backend, mock_client_class):
        mock_backend.read.return_value = pd.DataFrame(
            [{"_id": "old", "_last_modified": "old", "subject": True}]
        )
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.retrieve_docdb_records.side_effect = [
            [{"_id": "new", "_last_modified": "new"}],
            [{"_id": "new", "_last_modified": "new", "subject": {}}],
        ]

        result = metadata_core(force_update=True)

        self.assertEqual(result["_id"].tolist(), ["new"])
        self.assertEqual(mock_client.retrieve_docdb_records.call_count, 2)
        mock_client.aggregate_docdb_records.assert_not_called()


if __name__ == "__main__":
    unittest.main()