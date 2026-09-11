"""Unit tests for QC cache table."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import biodata_cache.registry as registry
from biodata_cache.backend import MemoryBackend
from biodata_cache.cache_table_helpers.qc import _fetch_qc_records, build_qc_rows, qc


@pytest.fixture(autouse=True)
def memory_backend():
    registry.BACKEND = MemoryBackend()


def _metric(name, *, stage="Processing", modality="behavior", value=None, reference=None, tags=None):
    return {
        "object_type": "QC metric",
        "name": name,
        "stage": stage,
        "modality": {"name": modality, "abbreviation": modality} if modality else None,
        "value": value,
        "reference": reference,
        "tags": tags,
        "status_history": [{"status": "Pass", "timestamp": "2026-01-01T00:00:00Z"}],
    }


def _asset(name, metrics, *, data_level="derived", modalities=("behavior",), created=None):
    return {
        "_id": name,
        "name": name,
        "location": f"s3://bucket/{name}",
        "data_description": {"data_level": data_level, "modalities": [{"abbreviation": m} for m in modalities]},
        "quality_control": {"metrics": metrics, "default_grouping": ["probe"]},
        "_created": created,
    }


def _basics(*assets):
    return pd.DataFrame(
        [
            {
                "name": asset["name"],
                "location": asset["location"],
                "data_level": asset["data_description"]["data_level"],
                "modalities": [m["abbreviation"] for m in asset["data_description"].get("modalities", [])],
                "created": asset.get("_created"),
            }
            for asset in assets
        ]
    )


def _sources(*pairs):
    return pd.DataFrame(pairs, columns=["name", "source_data", "pipeline_name", "processing_time"])


def test_build_qc_rows_selects_latest_terminal_chain_per_modality_and_tracks_downstream_versions():
    raw = _asset(
        "raw",
        [_metric("raw metric", stage="Raw", modality="behavior", value={"x": 1})],
        data_level="raw",
        created="2026-01-01",
    )
    old_behavior = _asset(
        "behavior-old",
        [
            _metric("raw metric", stage="Raw", modality="behavior", value={"x": 1}),
            _metric("behavior metric", value="old"),
        ],
        created="2026-01-02",
    )
    new_behavior = _asset(
        "behavior-new",
        [
            _metric("raw metric", stage="Raw", modality="behavior", value={"x": 1}),
            _metric("behavior metric", value="new"),
        ],
        created="2026-01-03",
    )
    pophys = _asset(
        "pophys",
        [
            _metric("raw metric", stage="Raw", modality="behavior", value={"x": 1}),
            _metric("pophys metric", modality="pophys", reference="figure.png"),
        ],
        modalities=("pophys",),
        created="2026-01-02",
    )
    records = [raw, old_behavior, new_behavior, pophys]
    sources = _sources(
        ("behavior-old", "raw", "pipeline", "2026-01-02_00-00-00"),
        ("behavior-new", "raw", "pipeline", "2026-01-03_00-00-00"),
        ("pophys", "raw", "pipeline", "2026-01-02_00-00-00"),
    )

    rows = build_qc_rows(records, _basics(raw, old_behavior, new_behavior, pophys), sources)

    assert {row["raw_asset_name"] for row in rows} == {"raw"}
    assert {row["name"] for row in rows} == {"raw metric", "behavior metric", "pophys metric"}
    behavior = next(row for row in rows if row["name"] == "behavior metric")
    assert behavior["asset_name"] == "behavior-new"
    assert behavior["downstream_asset_names"] == []
    raw_metric = next(row for row in rows if row["name"] == "raw metric")
    assert raw_metric["asset_name"] == "raw"
    assert set(raw_metric["downstream_asset_names"]) == {"behavior-new", "pophys"}
    pophys_metric = next(row for row in rows if row["name"] == "pophys metric")
    assert pophys_metric["reference"] == "figure.png"
    assert pophys_metric["asset_location"] == "s3://bucket/pophys"


def test_build_qc_rows_keeps_earliest_metric_in_a_downstream_chain():
    raw = _asset("raw", [_metric("shared", stage="Raw", value="origin")], data_level="raw", created="2026-01-01")
    middle = _asset(
        "middle",
        [_metric("shared", stage="Raw", value="origin"), _metric("middle-only", value=1)],
        created="2026-01-02",
    )
    leaf = _asset(
        "leaf", [_metric("shared", stage="Raw", value="origin"), _metric("middle-only", value=1)], created="2026-01-03"
    )
    rows = build_qc_rows(
        [raw, middle, leaf],
        _basics(raw, middle, leaf),
        _sources(
            ("middle", "raw", "pipeline", "2026-01-02_00-00-00"),
            ("leaf", "middle", "pipeline", "2026-01-03_00-00-00"),
        ),
    )

    shared = next(row for row in rows if row["name"] == "shared")
    middle_only = next(row for row in rows if row["name"] == "middle-only")
    assert shared["asset_name"] == "raw"
    assert shared["downstream_asset_names"] == ["middle", "leaf"]
    assert middle_only["asset_name"] == "middle"
    assert middle_only["downstream_asset_names"] == ["leaf"]


def test_qc_rows_preserve_full_metric_json_for_browser_rendering():
    raw = _asset("raw", [_metric("complex", value={"nested": [1, 2]}, tags={"suite": "a"})], data_level="raw")
    rows = build_qc_rows(
        [raw], _basics(raw), pd.DataFrame(columns=["name", "source_data", "pipeline_name", "processing_time"])
    )
    row = rows[0]
    assert row["metric_json"]
    assert row["tags"] == '{"suite": "a"}'
    assert row["value"] == '{"nested": [1, 2]}'


def test_fetch_qc_records_uses_50_record_batches():
    records = [{"_id": f"asset-{index}", "name": f"asset-{index}"} for index in range(101)]
    client = MagicMock()

    def retrieve(*, filter_query, projection, limit):
        if projection == {"_id": 1}:
            return [{"_id": record["_id"]} for record in records]
        ids = set(filter_query["_id"]["$in"])
        assert limit <= 50
        return [record for record in records if record["_id"] in ids]

    client.retrieve_docdb_records.side_effect = retrieve

    fetched = _fetch_qc_records(client)

    assert len(fetched) == len(records)
    calls = client.retrieve_docdb_records.call_args_list
    assert len(calls) == 4  # one ID query plus three data batches
    assert [call.kwargs["limit"] for call in calls[1:]] == [50, 50, 1]
    assert all(len(call.kwargs["filter_query"]["_id"]["$in"]) <= 50 for call in calls[1:])


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_cache_miss_with_force_update(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric 1",
                        "stage": "Processing",
                        "modality": {"name": "Test Modality", "abbreviation": "tm"},
                        "value": {"value": "pass", "status": "Pass"},
                        "tags": {"tag1": "value1"},
                        "status_history": [
                            {"status": "Pass", "evaluator": "test_user", "timestamp": "2025-01-01T00:00:00"}
                        ],
                    },
                    {
                        "object_type": "QC metric",
                        "name": "Test Metric 2",
                        "stage": "Acquisition",
                        "modality": {"name": "Test Modality 2", "abbreviation": "tm2"},
                        "value": None,
                        "tags": None,
                        "status_history": [
                            {"status": "Pending", "evaluator": "Pending review", "timestamp": "2025-01-01T00:00:00"}
                        ],
                    },
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert len(df) == 2
    assert df.iloc[0]["name"] == "Test Metric 1"
    assert df.iloc[1]["name"] == "Test Metric 2"
    assert df.iloc[0]["value"] == '{"status": "Pass", "value": "pass"}'


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_cache_hit(mock_client_class):
    cache_df = pd.DataFrame(
        {"name": ["Metric 1", "Metric 2"], "stage": ["Processing", "Acquisition"], "value": ["pass", "{dict}"]}
    )
    registry.BACKEND.write("qc/cached-asset", cache_df)
    df = qc("cached-asset", force_update=False)
    assert len(df) == 2
    assert df.iloc[0]["name"] == "Metric 1"
    mock_client_class.assert_not_called()


def test_qc_empty_cache_raises_error():
    df = qc("nonexistent-asset", force_update=False)
    assert df.empty


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_no_record_found(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = []
    assert qc("missing-asset", force_update=True).empty


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_no_metrics_in_record(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {"_id": "test-asset-002", "name": "test-asset", "quality_control": {}}
    ]
    assert qc("test-asset", force_update=True).empty


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_cache_persistence(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-004",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Persistent Metric",
                        "stage": "Processing",
                        "modality": {"name": "Test", "abbreviation": "t"},
                        "value": "test_value",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        }
    ]
    df1 = qc("test-asset", force_update=True)
    assert len(df1) == 1
    mock_client_instance.retrieve_docdb_records.reset_mock()
    df2 = qc("test-asset", force_update=False)
    assert len(df2) == 1
    assert df2.iloc[0]["name"] == "Persistent Metric"
    mock_client_instance.retrieve_docdb_records.assert_not_called()


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_multiple_assets_merge(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "asset1",
            "name": "asset1",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Metric A",
                        "stage": "Processing",
                        "modality": {"name": "Test", "abbreviation": "t"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        },
        {
            "_id": "asset2",
            "name": "asset2",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Metric B",
                        "stage": "Processing",
                        "modality": {"name": "Test", "abbreviation": "t"},
                        "value": "fail",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        },
    ]
    df = qc(force_update=True)
    assert len(df) == 2
    assert "asset_name" in df.columns
    assert df[df["name"] == "Metric A"].iloc[0]["asset_name"] == "asset1"
    assert df[df["name"] == "Metric B"].iloc[0]["asset_name"] == "asset2"


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_multiple_assets_from_cache(mock_client_class):
    cache_df1 = pd.DataFrame(
        {"name": ["Metric 1"], "stage": ["Processing"], "value": ["pass"], "asset_name": ["asset1"]}
    )
    cache_df2 = pd.DataFrame(
        {"name": ["Metric 2"], "stage": ["Acquisition"], "value": ["fail"], "asset_name": ["asset2"]}
    )
    registry.BACKEND.write("qc/test-raw", pd.concat([cache_df1, cache_df2], ignore_index=True))
    df = qc("test-raw", asset_names=["asset1", "asset2"], force_update=False)
    assert len(df) == 2
    assert "asset_name" in df.columns
    assert sorted(df["asset_name"].unique().tolist()) == ["asset1", "asset2"]
    mock_client_class.assert_not_called()


def test_qc_multiple_empty_assets_no_force_update():
    df = qc("nonexistent-subject", asset_names=["nonexistent1", "nonexistent2"], force_update=False)
    assert df.empty


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_single_asset_name_string(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "asset1",
            "name": "asset1",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Metric A",
                        "stage": "Processing",
                        "modality": {"name": "Test", "abbreviation": "t"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        },
        {
            "_id": "asset2",
            "name": "asset2",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Metric B",
                        "stage": "Processing",
                        "modality": {"name": "Test", "abbreviation": "t"},
                        "value": "fail",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        },
    ]
    df = qc("asset1", asset_names="asset1", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Metric A"
    assert df.iloc[0]["asset_name"] == "asset1"


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_missing_asset_names(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "asset1",
            "name": "asset1",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Metric A",
                        "stage": "Processing",
                        "modality": {"name": "Test", "abbreviation": "t"},
                        "value": "pass",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        },
    ]
    df = qc("asset1", asset_names=["asset1", "nonexistent"], force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "Metric A"


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_status_extracted_from_status_history(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Pass Metric",
                        "stage": "Processing",
                        "modality": None,
                        "value": "ok",
                        "tags": None,
                        "status_history": [
                            {"status": "Pending", "timestamp": "2025-01-01T00:00:00"},
                            {"status": "Pass", "timestamp": "2025-01-02T00:00:00"},
                        ],
                    },
                    {
                        "object_type": "QC metric",
                        "name": "Fail Metric",
                        "stage": "Raw data",
                        "modality": None,
                        "value": "bad",
                        "tags": None,
                        "status_history": [{"status": "Fail", "timestamp": "2025-01-01T00:00:00"}],
                    },
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert "status" in df.columns
    assert "status_history" not in df.columns
    assert df[df["name"] == "Pass Metric"].iloc[0]["status"] == "Pass"
    assert df[df["name"] == "Fail Metric"].iloc[0]["status"] == "Fail"


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_numeric_value_converted_to_string(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Numeric Metric",
                        "stage": "Processing",
                        "modality": None,
                        "value": 42,
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ]
            },
        }
    ]
    df = qc("test-asset", force_update=True)
    assert len(df) == 1
    assert df.iloc[0]["value"] == "42"


@patch("aind_data_access_api.document_db.MetadataDbClient")
def test_qc_tag_statuses_cached_separately(mock_client_class):
    mock_client_instance = MagicMock()
    mock_client_class.return_value = mock_client_instance
    mock_client_instance.retrieve_docdb_records.return_value = [
        {
            "_id": "test-asset-001",
            "name": "test-asset",
            "subject": {"subject_id": "test-subject"},
            "quality_control": {
                "metrics": [
                    {
                        "object_type": "QC metric",
                        "name": "Metric A",
                        "stage": "Processing",
                        "modality": None,
                        "value": "ok",
                        "tags": None,
                        "status_history": [{"status": "Pass", "timestamp": "2025-01-01T00:00:00"}],
                    }
                ],
                "status": {"tagA:Suite": "Pass", "tagB:Suite": "Fail"},
            },
        }
    ]
    qc("test-asset", force_update=True)
    tag_df = registry.BACKEND.read("qc_tag_status/test-subject")
    assert not tag_df.empty
    assert set(tag_df["tag"].tolist()) == {"tagA:Suite", "tagB:Suite"}
    assert tag_df[tag_df["tag"] == "tagA:Suite"]["status"].iloc[0] == "Pass"
