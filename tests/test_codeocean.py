"""Regression tests for scoped Code Ocean metadata computations."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import biodata_cache.registry as registry
import biodata_cache.sync as sync
from biodata_cache import asset_basics, platform_fib_traces, platform_smartspim_fiber_ccf, platform_smartspim_qc_metrics
from biodata_cache.backend import MemoryBackend
from biodata_cache.codeocean import CodeOceanBackend


def record(name="SmartSPIM_1_stitched_2026", instrument="SmartSPIM-1"):
    """Return a canonical record covering both QC table contracts."""
    return {
        "_id": name,
        "_created": "2026-01-01",
        "_last_modified": "2026-01-02",
        "name": name,
        "location": f"s3://bucket/{name}",
        "other_identifiers": {"Code Ocean": "co-id"},
        "subject": {"subject_id": "1"},
        "data_description": {"name": name, "data_level": "derived", "modalities": [{"abbreviation": "SPIM"}]},
        "instrument": {"instrument_id": instrument},
        "acquisition": {"channels": [{"channel_name": "488"}], "acquisition_start_time": "2026-01-01T10:00:00Z"},
        "procedures": {
            "subject_procedures": [
                {
                    "procedures": [
                        {
                            "object_type": "Probe implant",
                            "implanted_device": {"object_type": "Fiber probe", "name": fiber},
                            "device_config": {"primary_targeted_structure": {"acronym": "ACB"}},
                        }
                        for fiber in ("Fiber 0", "Fiber 1")
                    ]
                }
            ]
        },
        "quality_control": {
            "metrics": [
                {
                    "name": "Fiber 0 CCF Location",
                    "value": 'json:{"AP": 1, "ML": null, "DV": "3"}',
                    "reference": "https://example.org/ccf",
                    "status_history": [
                        {"status": "Pending", "timestamp": "2026-01-01", "evaluator": "a"},
                        {"status": "Pass", "timestamp": "2026-01-02", "evaluator": "b"},
                    ],
                },
                {
                    "name": "Image and tissue quality",
                    "stage": "Processing",
                    "value": {"value": 0.75},
                    "status_history": [{"status": "Pass", "timestamp": "2026-01-02", "evaluator": "b"}],
                },
                {"name": "488 brightness", "value": 12.5, "tags": {"Channel": "488-tag"}},
                {"name": "Unrelated metric", "value": 99},
            ]
        },
    }


def mount(root, data, manifest=True, directory=None, attached=True):
    """Write either a complete manifest or component metadata mount."""
    path = root / (directory or data["name"])
    path.mkdir(parents=True)
    if manifest:
        (path / "metadata.json").write_text(json.dumps(data))
    else:
        for key in ("subject", "data_description", "instrument", "acquisition", "procedures", "quality_control"):
            (path / f"{key}.json").write_text(json.dumps(data[key]))
    if attached:
        datasets_file = root.parent / ".codeocean" / ".datasets.json"
        datasets_file.parent.mkdir(exist_ok=True)
        datasets = json.loads(datasets_file.read_text())["attached_datasets"] if datasets_file.exists() else []
        datasets.append(
            {"id": f"dataset-{path.relative_to(root).as_posix()}", "mount": path.relative_to(root).as_posix()}
        )
        write_datasets(datasets_file, sorted(datasets, key=lambda dataset: dataset["mount"]))
    return path


def write_datasets(path, datasets):
    """Write the capsule attachment manifest fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "attached_datasets": datasets}))


@pytest.fixture
def local(tmp_path, monkeypatch):
    """Install a scoped backend with qualifying and unrelated attached assets."""
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data"
    canonical = record()
    mount(root, canonical)
    exa = record("ExaSPIM_2", "ExaSPIM-1")
    mount(root, exa)
    unrelated = record("unrelated", "Other")
    unrelated["data_description"]["modalities"] = [{"abbreviation": "ecephys"}]
    mount(root, unrelated)
    backend = CodeOceanBackend(root, tmp_path / "results", tmp_path / ".codeocean/.datasets.json")
    monkeypatch.setattr(registry, "BACKEND", backend)
    monkeypatch.setattr(sync, "BACKEND", backend)
    return backend, [exa, canonical, unrelated]


def test_qc_frames_equal_docdb_boundary_and_persist(local, monkeypatch):
    backend, records = local
    with patch("aind_data_access_api.document_db.MetadataDbClient") as client:
        monkeypatch.setattr(registry, "BACKEND", MemoryBackend())
        client.return_value.retrieve_docdb_records.return_value = [records[1]]
        expected_ccf = platform_smartspim_fiber_ccf(force_update=True)
        client.return_value.retrieve_docdb_records.return_value = records
        expected_metrics = platform_smartspim_qc_metrics(force_update=True)
        expected_basics = asset_basics(force_update=True)
    monkeypatch.setattr(registry, "BACKEND", backend)
    with (
        patch("boto3.client", side_effect=AssertionError("network")),
        patch("aind_data_access_api.document_db.MetadataDbClient", side_effect=AssertionError("network")),
    ):
        assert_frame_equal(asset_basics(), expected_basics)
        assert_frame_equal(platform_smartspim_fiber_ccf(), expected_ccf)
        assert {path.name for path in backend.results_root.iterdir()} == {"platform_smartspim_fiber_ccf.pqt"}
        assert_frame_equal(platform_smartspim_qc_metrics(), expected_metrics)
        fresh = CodeOceanBackend(backend.data_root, backend.results_root.parent, backend.datasets_file)
        monkeypatch.setattr(registry, "BACKEND", fresh)
        assert_frame_equal(platform_smartspim_fiber_ccf(), expected_ccf)
        assert_frame_equal(platform_smartspim_qc_metrics(), expected_metrics)
    assert {p.name for p in backend.results_root.iterdir()} == {
        "platform_smartspim_fiber_ccf.pqt",
        "platform_smartspim_qc_metrics.pqt",
    }
    assert not backend._json_store


def test_scoped_basics_filters_and_refresh(local):
    backend, _ = local
    with (
        patch("boto3.client", side_effect=AssertionError("network")),
        patch("aind_data_access_api.document_db.MetadataDbClient", side_effect=AssertionError("network")),
    ):
        assert len(asset_basics()) == 3
        page, total = asset_basics(
            modality="spim",
            data_level="derived",
            columns=["name", "modalities"],
            acquisition_start_after="2026-01-01",
            acquisition_start_before="2026-01-02",
            include_total=True,
            limit=1,
            offset=1,
        )
        assert total == 2
        assert page["name"].tolist() == ["SmartSPIM_1_stitched_2026"]
        assert page["modalities"].tolist() == [["SPIM"]]
        assert asset_basics(name="unrelated", columns=["name"])["name"].tolist() == ["unrelated"]
        assert asset_basics(name_contains="STITCHED", columns=["name"])["name"].tolist() == [
            "SmartSPIM_1_stitched_2026"
        ]
        asset_basics(force_update=True)
    assert not backend.results_root.exists()


def test_manifest_components_and_identity_defaults(tmp_path):
    data = record()
    source = mount(tmp_path / "data", data, manifest=False)
    backend = CodeOceanBackend(tmp_path / "data", tmp_path / "results", tmp_path / ".codeocean/.datasets.json")
    result = backend.load_records()[0]
    assert result["name"] == data["name"]
    assert result["location"] == str(source)
    assert result["_id"] is None and result["_last_modified"] is None and result["_created"] is None
    assert result["other_identifiers"] == {"Code Ocean": f"dataset-{data['name']}"}
    (source / "metadata.json").write_text(json.dumps(data))
    assert backend.load_records()[0] == data | {"processing": {}}
    (source / "quality_control.json").write_text('{"metrics": []}')
    assert backend.load_records()[0]["quality_control"] == {"metrics": []}
    (source / "quality_control.json").write_text("not json")
    with pytest.raises(ValueError, match="quality_control.json"):
        backend.load_records()


def test_attachment_resolution_and_scope_isolation(tmp_path):
    root = tmp_path / "data"
    datasets_file = tmp_path / ".codeocean/.datasets.json"
    dataset_id = "c76cfb05-c3f4-4871-9cae-b749efcf9a41"
    mount_name = "869614_2026-10-07_19-03-02"
    data = record("SmartSPIM_869614_stitched_2026")
    source = mount(root, data, directory=mount_name)
    mount(root, record("unlisted"), attached=False)
    write_datasets(datasets_file, [{"id": dataset_id, "mount": mount_name}])
    backend = CodeOceanBackend(root, tmp_path / "results", datasets_file)
    for identity in (dataset_id, mount_name, data["name"], data["location"]):
        assert backend.resolve_asset(identity) == source
    assert [r["name"] for r in backend.load_records()] == [data["name"]]
    with pytest.raises(ValueError, match="found 0"):
        backend.resolve_asset("unlisted")
    second = mount(root, record("other"), attached=False)
    write_datasets(datasets_file, [{"id": "other-id", "mount": second.name}])
    other = CodeOceanBackend(root, tmp_path / "results", datasets_file)
    assert backend.results_root != other.results_root
    assert backend.resolve_asset(dataset_id) == source
    with pytest.raises(ValueError, match="separate"):
        CodeOceanBackend(root, root / "results", datasets_file)


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {},
        {"version": 2, "attached_datasets": []},
        {"version": True, "attached_datasets": []},
        {"version": 1, "attached_datasets": []},
        {"version": 1, "attached_datasets": {}},
        {"version": 1, "attached_datasets": [None]},
        {"version": 1, "attached_datasets": [{"mount": "asset"}]},
        *[
            {"version": 1, "attached_datasets": [{"id": "id", "mount": value}]}
            for value in (None, "", "../asset", "/asset", "bucket/../asset", "bucket\\asset")
        ],
        {"version": 1, "attached_datasets": [{"id": "id", "mount": "asset"}, {"id": "id", "mount": "other"}]},
        {"version": 1, "attached_datasets": [{"id": "id", "mount": "asset"}, {"id": "other", "mount": "asset"}]},
    ],
)
def test_invalid_attachment_manifest_rejected(tmp_path, manifest):
    root = tmp_path / "data"
    mount(root, record("asset"))
    datasets_file = tmp_path / ".codeocean/.datasets.json"
    datasets_file.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        CodeOceanBackend(root, tmp_path / "results", datasets_file)


def test_missing_attachment_file_and_mount_rejected(tmp_path):
    datasets_file = tmp_path / ".codeocean/.datasets.json"
    with pytest.raises(ValueError, match=".datasets.json"):
        CodeOceanBackend(tmp_path / "data", tmp_path / "results", datasets_file)
    write_datasets(datasets_file, [{"id": "id", "mount": "missing"}])
    with pytest.raises(FileNotFoundError, match="mount is missing"):
        CodeOceanBackend(tmp_path / "data", tmp_path / "results", datasets_file)


def test_symlink_and_invalid_metadata_rejected(tmp_path):
    root = tmp_path / "data"
    source = mount(root, record())
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (source / "quality_control.json").symlink_to(outside)
    backend = CodeOceanBackend(root, tmp_path / "results", tmp_path / ".codeocean/.datasets.json")
    with pytest.raises(ValueError, match="escapes"):
        backend.load_records()
    (source / "quality_control.json").unlink()
    (source / "quality_control.json").write_text("[]")
    with pytest.raises(ValueError, match="JSON object"):
        backend.load_records()
    (source / "quality_control.json").write_text('{"metrics": {}}')
    with pytest.raises(ValueError, match="metrics list"):
        backend.load_records()
    (source / "quality_control.json").write_text('{"metrics": [{"status_history": ["invalid"]}]}')
    with pytest.raises(ValueError, match="status_history"):
        backend.load_records()
    (root / "escape").symlink_to(tmp_path)
    write_datasets(tmp_path / ".codeocean/.datasets.json", [{"id": "escape-id", "mount": "escape"}])
    with pytest.raises(ValueError, match="escapes"):
        CodeOceanBackend(root, tmp_path / "results", tmp_path / ".codeocean/.datasets.json")


def test_cache_hit_force_and_empty_results(local):
    backend, records = local
    original = platform_smartspim_fiber_ccf()
    updated = copy.deepcopy(records[1])
    updated["quality_control"]["metrics"][0]["value"] = {"AP": 42}
    source = backend.resolve_asset(updated["name"])
    (source / "metadata.json").write_text(json.dumps(updated))
    assert_frame_equal(platform_smartspim_fiber_ccf(), original)
    assert platform_smartspim_fiber_ccf(force_update=True)["ap"].iloc[0] == 42
    empty = pd.DataFrame(columns=["test"])
    backend.write("platform_smartspim_qc_metrics", empty)
    with patch.object(backend, "load_records", side_effect=AssertionError("should reuse empty output")):
        assert_frame_equal(platform_smartspim_qc_metrics(), empty)
    assert backend.cache_exists("platform_smartspim_qc_metrics")
    assert Path(backend.get_location("platform_smartspim_qc_metrics")).is_file()


def test_sync_and_unsupported_scope(local):
    backend, _ = local
    with (
        patch("boto3.client", side_effect=AssertionError("network")),
        patch("aind_data_access_api.document_db.MetadataDbClient", side_effect=AssertionError("network")),
    ):
        sync.run_sync_job("asset_basics")
        sync.run_sync_job("smartspim")
        for job in ("fast", "fib_traces", "operations"):
            with pytest.raises(NotImplementedError):
                sync.run_sync_job(job)
        with pytest.raises(NotImplementedError):
            sync.update_all_tables()
        with pytest.raises(NotImplementedError):
            platform_fib_traces("missing", force_update=True)
    for method, args in (
        (backend.read, ("platform_fib_traces/asset",)),
        (backend.read, (["platform_smartspim_fiber_ccf"],)),
        (backend.get_location, ("asset_basics",)),
        (backend.put_registry_fragment, ("table", "{}")),
        (backend.register_version, ()),
        (backend.put_json, ("registry", "{}")),
        (backend.put_bytes, ("file", b"", "text/plain")),
        (backend.partition_exists, ("platform_fib_traces/asset",)),
        (backend.get_versions_index, ()),
    ):
        with pytest.raises(NotImplementedError):
            method(*args)
    assert not backend._json_store
    assert len(list(backend.results_root.glob("*.pqt"))) == 2


def test_backend_selection_fresh_import_blocks_network(tmp_path):
    root = tmp_path / "data"
    mount(root, record(), manifest=False)
    environment = os.environ | {"BIODATA_CACHE_BACKEND": "memory"}
    script = """
import importlib
import os
import sys
from pathlib import Path
import boto3
class BlockDocDB:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('aind_data_access_api'):
            raise AssertionError('DocDB import')
sys.meta_path.insert(0, BlockDocDB())
def no_client(*args, **kwargs):
    raise AssertionError('AWS client')
boto3.client = no_client
import biodata_cache as cache
import biodata_cache.codeocean as local
import biodata_cache.registry as registry
local.DATA_ROOT = Path('data')
local.RESULTS_ROOT = Path('results')
os.environ['BIODATA_CACHE_BACKEND'] = ' CodeOcean '
importlib.reload(registry)
BACKEND = registry.BACKEND
assert BACKEND.__class__.__name__ == 'CodeOceanBackend'
assert len(cache.asset_basics()) == 1
assert len(cache.platform_smartspim_fiber_ccf()) == 2
assert len(cache.platform_smartspim_qc_metrics()) == 2
"""
    result = subprocess.run(
        [sys.executable, "-c", script], env=environment, cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
