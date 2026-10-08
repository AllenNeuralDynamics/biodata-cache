"""Tests for metadata-seeded exaSPIM intermediate-folder discovery."""

import importlib
import json
from unittest.mock import MagicMock

import pandas as pd
import pyarrow as pa
import pytest
from botocore.exceptions import ClientError

from biodata_cache.backend import MemoryBackend
from biodata_cache.sync import run_sync_job

mod = importlib.import_module("biodata_cache.cache_table_helpers.platform_exaspim_intermediates")
RAW = {
    "name": "exaSPIM_123_2026-01-01_12-00-00",
    "location": "s3://bucket/nested/raw/",
    "subject_id": "123",
    "project_name": "test",
}
CANDIDATE = {
    "name": RAW["name"] + "_processed_2026-02-01_12-00-00",
    "location": "s3://other/custom/processed/",
    "discovery_source": "docdb",
    "_id": "id",
}


def s3_with_folders(present):
    """Mock prefix existence without downloading data."""
    s3 = MagicMock()
    s3.list_objects_v2.side_effect = lambda **kw: {
        "KeyCount": int(any(kw["Prefix"].endswith(folder) for folder in present))
    }
    return s3


@pytest.mark.parametrize(
    "keys,status,eligible,has_intermediates",
    [
        (list(mod.FOLDERS), "ok", True, True),
        ([*mod.REQUIRED_KEYS, "denoised_present"], "ok", True, True),
        (["flatfield_present"], "missing_required", False, True),
        (list(mod.REQUIRED_KEYS), "no_intermediates", False, False),
        ([], "missing_required", False, False),
    ],
)
def test_folder_checks(keys, status, eligible, has_intermediates):
    s3 = s3_with_folders([mod.FOLDERS[key] for key in keys])
    row = mod._inspect(s3, RAW, CANDIDATE)
    assert row["status"] == status
    assert row["eligible_for_cleanup"] is eligible
    assert row["has_intermediates"] is has_intermediates
    assert row["docdb_id"] == "id"
    assert len(row["intermediate_uris"]) == sum(key in keys for key in mod.INTERMEDIATE_KEYS)
    assert row["output_uris"] == (row["intermediate_uris"] if eligible else [])
    assert row["missing_required_folders"] == [mod.FOLDERS[key] for key in mod.REQUIRED_KEYS if key not in keys]
    assert s3.list_objects_v2.call_count == 4
    for call in s3.list_objects_v2.call_args_list:
        assert call.kwargs["Bucket"] == "other"
        assert call.kwargs["Prefix"].startswith("custom/processed/")
        assert call.kwargs["MaxKeys"] == 1


def test_s3_errors_preserve_unknowns_and_confirmed_presence():
    s3 = s3_with_folders(mod.FOLDERS.values())
    normal = s3.list_objects_v2.side_effect

    def listing(**kw):
        if kw["Prefix"].endswith(mod.FOLDERS["fused_present"]):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "secret-url"}}, "ListObjectsV2")
        return normal(**kw)

    s3.list_objects_v2.side_effect = listing
    row = mod._inspect(s3, RAW, CANDIDATE)
    assert row["status"] == "s3_error"
    assert row["error_code"] == "AccessDenied"
    assert row["fused_present"] is None
    assert row["has_intermediates"] is True
    assert row["eligible_for_cleanup"] is None
    assert row["output_uris"] == []
    assert len(row["intermediate_uris"]) == 2


def test_docdb_snapshot_is_shared_across_chains_and_new_lineage_is_local():
    client = MagicMock()
    first = dict(CANDIDATE, data_description={"source_data": [RAW["name"]]})
    second = dict(CANDIDATE, name="exaSPIM_renamed-stage", data_description={"source_data": [first["name"]]})
    client.retrieve_docdb_records.return_value = [first, first, second]
    raws = [RAW["name"], *[f"exaSPIM_{i}" for i in range(100)]]
    snapshot, edges = mod._docdb_snapshot(client, raws, pd.DataFrame())
    candidates = mod._docdb_candidates(snapshot, edges, RAW["name"])
    assert {r["name"] for r in candidates} == {first["name"], second["name"]}
    assert all(mod._docdb_candidates(snapshot, edges, name) == [] for name in raws[1:])
    client.retrieve_docdb_records.assert_called_once()
    query = client.retrieve_docdb_records.call_args.kwargs["filter_query"]
    assert query == {"data_description.data_level": "derived", "name": {"$regex": "^exaSPIM_"}}
    assert client.retrieve_docdb_records.call_args.kwargs["limit"] == 0


def test_cached_renamed_descendants_are_batched_and_cycles_are_safe():
    first = dict(CANDIDATE, name="renamed-first-stage")
    second = dict(CANDIDATE, name="renamed-second-stage")
    links = pd.DataFrame(
        [
            {"name": first["name"], "source_data": RAW["name"]},
            {"name": second["name"], "source_data": first["name"]},
            {"name": first["name"], "source_data": second["name"]},
        ]
    )
    client = MagicMock()
    client.retrieve_docdb_records.side_effect = [[], [first, second]]
    snapshot, edges = mod._docdb_snapshot(client, [RAW["name"]], links)
    assert {r["name"] for r in mod._docdb_candidates(snapshot, edges, RAW["name"])} == {first["name"], second["name"]}
    assert client.retrieve_docdb_records.call_count == 2
    query = client.retrieve_docdb_records.call_args.kwargs["filter_query"]
    assert query["name"]["$in"] == sorted([first["name"], second["name"]])


def test_prefixed_stage_without_provenance_still_seeds_renamed_descendants():
    first = dict(CANDIDATE)
    second = dict(CANDIDATE, name="renamed-stage")
    links = pd.DataFrame([{"name": second["name"], "source_data": first["name"]}])
    client = MagicMock()
    client.retrieve_docdb_records.side_effect = [[first], [second]]
    snapshot, edges = mod._docdb_snapshot(client, [RAW["name"]], links)
    assert {r["name"] for r in mod._docdb_candidates(snapshot, edges, RAW["name"])} == {first["name"], second["name"]}


def test_docdb_candidates_take_precedence_over_s3_discovery():
    s3 = s3_with_folders(mod.FOLDERS.values())
    rows = mod._assess_candidates(s3, RAW, [CANDIDATE])
    assert rows[0]["discovery_source"] == "docdb"
    s3.get_paginator.assert_not_called()


def test_s3_fallback_paginates_only_the_seeded_chain():
    s3 = s3_with_folders(mod.FOLDERS.values())
    prefix = "nested/" + CANDIDATE["name"] + "/"
    s3.get_paginator.return_value.paginate.return_value = [
        {"CommonPrefixes": [{"Prefix": prefix}]},
        {"CommonPrefixes": [{"Prefix": prefix}, {"Prefix": prefix.replace("2026-02-01", "2026-03-01")}]},
    ]
    rows = mod._assess_candidates(s3, RAW, [])
    assert len(rows) == 2
    assert all(r["discovery_source"] == "s3" and r["status"] == "ok" for r in rows)
    assert rows[0]["location"] == "s3://bucket/" + prefix.rstrip("/")
    s3.get_paginator.return_value.paginate.assert_called_once_with(
        Bucket="bucket", Prefix="nested/" + RAW["name"] + "_processed_", Delimiter="/"
    )


def test_absent_candidates_and_discovery_failures_are_distinct():
    s3 = MagicMock()
    s3.get_paginator.return_value.paginate.return_value = [{}]
    row = mod._assess_candidates(s3, RAW, [])[0]
    assert row["status"] == "no_processed"
    assert row["eligible_for_cleanup"] is None
    assert row["name"] is None
    s3.get_paginator.return_value.paginate.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied"}}, "ListObjectsV2"
    )
    assert mod._assess_candidates(s3, RAW, [])[0]["status"] == "s3_error"
    assert mod._assess_candidates(s3, dict(RAW, location=None), [])[0]["status"] == "invalid_location"
    assert mod._inspect(s3, RAW, dict(CANDIDATE, location="https://bad"))["status"] == "invalid_location"


def setup_builder(monkeypatch):
    """Install an isolated cache, metadata client, and bounded S3 mock."""
    backend = MemoryBackend()
    monkeypatch.setattr(mod.registry, "BACKEND", backend)
    basics = pd.DataFrame([dict(RAW, instrument_id="ExaSPIM1"), dict(RAW, name="other", instrument_id="SmartSPIM1")])
    basics_fn = MagicMock(return_value=basics)
    monkeypatch.setattr(mod, "asset_basics", basics_fn)
    client = MagicMock()
    client.retrieve_docdb_records.return_value = [CANDIDATE]
    monkeypatch.setattr("aind_data_access_api.document_db.MetadataDbClient", MagicMock(return_value=client))
    s3 = s3_with_folders(mod.FOLDERS.values())
    monkeypatch.setattr(mod.boto3, "client", MagicMock(return_value=s3))
    return backend, basics_fn, client, s3


def test_refresh_rechecks_deleted_folders_and_filtered_read_is_unlimited(monkeypatch):
    backend, basics_fn, client, s3 = setup_builder(monkeypatch)
    df = mod.platform_exaspim_intermediates(force_update=True, workers=1)
    assert list(df.raw_name) == [RAW["name"]]
    assert bool(df.iloc[0].eligible_for_cleanup)
    assert client.retrieve_docdb_records.call_count == 1
    assert basics_fn.call_args.kwargs["limit"] is None
    assert basics_fn.call_args.kwargs["modality"] == "SPIM"
    assert basics_fn.call_args.kwargs["data_level"] == "raw"
    s3.list_objects_v2.side_effect = lambda **kw: {"KeyCount": int("fusion/" in kw["Prefix"])}
    refreshed = mod.platform_exaspim_intermediates(force_update=True, workers=1)
    assert refreshed.iloc[0].status == "no_intermediates"
    assert not bool(refreshed.iloc[0].eligible_for_cleanup)
    calls = client.retrieve_docdb_records.call_count
    pd.testing.assert_frame_equal(mod.platform_exaspim_intermediates(), refreshed)
    assert client.retrieve_docdb_records.call_count == calls
    assert backend.cache_exists("platform_exaspim_intermediates")


def test_docdb_failure_preserves_previous_cache(monkeypatch):
    backend, _, client, _ = setup_builder(monkeypatch)
    old = mod._frame([dict(mod._empty_row(RAW), status="no_processed")])
    backend.write("platform_exaspim_intermediates", old)
    client.retrieve_docdb_records.side_effect = RuntimeError("DocDB unavailable")
    with pytest.raises(RuntimeError, match="DocDB unavailable"):
        mod.platform_exaspim_intermediates(force_update=True)
    pd.testing.assert_frame_equal(backend.read("platform_exaspim_intermediates"), old)


def test_sync_job_publishes_matching_schema_and_empty_types(monkeypatch):
    backend, basics_fn, _, s3 = setup_builder(monkeypatch)
    basics_fn.return_value = basics_fn.return_value.iloc[:0]
    monkeypatch.setattr("biodata_cache.sync.BACKEND", backend)
    run_sync_job("exaspim_intermediates")
    df = backend.read("platform_exaspim_intermediates")
    assert df.empty
    s3.list_objects_v2.assert_not_called()
    entry = json.loads(backend.list_registry_fragments()[0])
    assert entry["name"] == "platform_exaspim_intermediates"
    assert entry["type"] == "metadata"
    assert not entry["partitioned"]
    assert [c["name"] for c in entry["columns"]] == list(df.columns)
    schema = pa.Table.from_pandas(df, preserve_index=False).schema
    assert schema.field("eligible_for_cleanup").type == pa.bool_()
    assert schema.field("output_uris").type == pa.list_(pa.string())
    assert schema.field("checked_at").type.tz == "UTC"


def test_missing_cache_and_invalid_workers(monkeypatch):
    monkeypatch.setattr(mod.registry, "BACKEND", MemoryBackend())
    with pytest.raises(ValueError, match="force_update"):
        mod.platform_exaspim_intermediates()
    with pytest.raises(ValueError, match="workers"):
        mod.platform_exaspim_intermediates(force_update=True, workers=0)
