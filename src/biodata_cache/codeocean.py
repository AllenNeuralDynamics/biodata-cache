"""Scoped metadata sources and local results for Code Ocean capsules."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from biodata_cache.backend import MemoryBackend

DATA_ROOT = Path("/data")
RESULTS_ROOT = Path("/results/biodata-cache")
DATASETS_FILE = Path(".codeocean/.datasets.json")

COMPONENTS = ("subject", "data_description", "procedures", "instrument", "acquisition", "processing", "quality_control")
SUPPORTED_TABLES = frozenset({"asset_basics", "platform_smartspim_fiber_ccf", "platform_smartspim_qc_metrics"})


class CodeOceanBackend(MemoryBackend):
    """Read attached metadata and materialize only supported scoped QC results."""

    def __init__(self, data_root=None, results_root=None, datasets_file=None):
        """Use capsule attachment metadata and fixed roots, with path overrides for tests."""
        super().__init__()
        self.data_root = Path(DATA_ROOT if data_root is None else data_root).resolve()
        results = Path(RESULTS_ROOT if results_root is None else results_root).resolve()
        self.datasets_file = Path(DATASETS_FILE if datasets_file is None else datasets_file).resolve()
        if results == self.data_root or self.data_root in results.parents or results in self.data_root.parents:
            raise ValueError("Code Ocean results root must be separate from the data root")
        self._datasets = self._load_datasets()
        self._sources = [(dataset["id"], self._inside(self.data_root / dataset["mount"])) for dataset in self._datasets]
        if len({path for _, path in self._sources}) != len(self._sources):
            raise ValueError(f"Duplicate Code Ocean dataset mounts in {self.datasets_file}")
        for dataset, (_, mount) in zip(self._datasets, self._sources, strict=True):
            if not mount.is_dir():
                raise FileNotFoundError(f"Code Ocean dataset {dataset['id']!r} mount is missing: {mount}")
        scope = json.dumps(sorted((identity, str(path)) for identity, path in self._sources))
        self.results_root = results / hashlib.sha256(scope.encode()).hexdigest()[:20]

    def _load_datasets(self) -> list[dict]:
        """Read the explicit attachment list without discovering unrelated directories."""
        manifest = self._read_object(self.datasets_file, input_file=False)
        if type(manifest.get("version")) is not int or manifest["version"] != 1:
            raise ValueError(f"Unsupported Code Ocean datasets version in {self.datasets_file}")
        datasets = manifest.get("attached_datasets")
        if not isinstance(datasets, list) or not datasets:
            raise ValueError(f"Expected a non-empty attached_datasets list in {self.datasets_file}")
        ids = set()
        for dataset in datasets:
            if not isinstance(dataset, dict) or not isinstance(dataset.get("id"), str) or not dataset["id"]:
                raise ValueError(f"Invalid Code Ocean dataset id in {self.datasets_file}")
            mount = dataset.get("mount")
            if (
                not isinstance(mount, str)
                or not mount
                or "\\" in mount
                or any(part in {"", ".", ".."} for part in mount.split("/"))
            ):
                raise ValueError(f"Unsafe Code Ocean dataset mount {mount!r} in {self.datasets_file}")
            if dataset["id"] in ids:
                raise ValueError(f"Duplicate Code Ocean dataset id {dataset['id']!r} in {self.datasets_file}")
            ids.add(dataset["id"])
        return datasets

    def _inside(self, path: Path) -> Path:
        """Reject paths or symlinks outside the mounted input root."""
        resolved = path.resolve()
        if resolved != self.data_root and self.data_root not in resolved.parents:
            raise ValueError(f"Code Ocean input path escapes data root: {path}")
        return resolved

    def resolve_asset(self, identity: str) -> Path:
        """Resolve an attached dataset by ID, mount, or supplied metadata identity."""
        records = self.load_records()
        matches = [
            mount
            for dataset, (_, mount), record in zip(self._datasets, self._sources, records, strict=True)
            if identity in {dataset["id"], dataset["mount"], record["name"], record["location"]}
        ]
        if len(matches) != 1:
            raise ValueError(f"Code Ocean asset {identity!r}: expected one attached mount, found {len(matches)}")
        return matches[0]

    def _read_object(self, path: Path, *, input_file: bool = True) -> dict:
        """Read a JSON object with an actionable file-level error."""
        if input_file:
            self._inside(path)
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read Code Ocean metadata {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Code Ocean metadata must be a JSON object: {path}")
        return value

    def _validate_record(self, record: dict, mount: Path) -> None:
        """Validate containers consumed by the shared builders without a network schema lookup."""

        def object_list(value, field, string_items=False):
            """Validate one metadata array and its object entries."""
            if value is None:
                return []
            if not isinstance(value, list) or any(
                not isinstance(item, (dict, str) if string_items else dict) for item in value
            ):
                raise ValueError(f"Invalid {field} list in metadata for {mount}")
            return value

        for component, field, strings in (
            ("data_description", "modalities", False),
            ("data_description", "investigators", False),
            ("acquisition", "channels", True),
            ("acquisition", "experimenters", True),
            ("processing", "data_processes", False),
        ):
            object_list(record[component].get(field), f"{component}.{field}", strings)
        for surgery in object_list(record["procedures"].get("subject_procedures"), "procedures.subject_procedures"):
            for procedure in object_list(surgery.get("procedures"), "procedures.subject_procedures.procedures"):
                for key in ("implanted_device", "device_config"):
                    if procedure.get(key) is not None and not isinstance(procedure[key], dict):
                        raise ValueError(f"Invalid procedures.{key} object in metadata for {mount}")
                structure = (procedure.get("device_config") or {}).get("primary_targeted_structure")
                if structure is not None and not isinstance(structure, dict):
                    raise ValueError(f"Invalid primary_targeted_structure object in metadata for {mount}")
        for metric in object_list(record["quality_control"].get("metrics"), "quality_control.metrics"):
            object_list(metric.get("status_history"), "quality_control.metrics.status_history")
        instrument = record["instrument"].get("instrument_id")
        if instrument is not None and not isinstance(instrument, str):
            raise ValueError(f"Invalid instrument.instrument_id string in metadata for {mount}")
        for value, field in (
            (record.get("other_identifiers"), "other_identifiers"),
            (record["subject"].get("subject_details"), "subject.subject_details"),
            (record["acquisition"].get("subject_details"), "acquisition.subject_details"),
        ):
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"Invalid {field} object in metadata for {mount}")

    def load_records(self) -> list[dict]:
        """Assemble canonical metadata records for datasets listed in the capsule attachment file only."""
        records = []
        names = set()
        for identity, mount in self._sources:
            manifest = mount / "metadata.json"
            record = self._read_object(manifest) if manifest.exists() else {}
            for component in COMPONENTS:
                path = mount / f"{component}.json"
                if path.exists():
                    record[component] = self._read_object(path)
                value = record.get(component)
                if value is not None and not isinstance(value, dict):
                    raise ValueError(f"Invalid {component} object in {manifest}")
                record[component] = value or {}
            if not record["data_description"]:
                raise ValueError(f"Missing data_description metadata for Code Ocean asset {identity!r} at {mount}")
            self._validate_record(record, mount)
            record["name"] = record.get("name") or record["data_description"].get("name") or mount.name
            if not isinstance(record["name"], str) or record["name"] in names:
                raise ValueError(f"Invalid or duplicate asset name {record['name']!r} at {mount}")
            names.add(record["name"])
            record["location"] = record.get("location") or str(mount)
            for field in ("_id", "_last_modified", "_created"):
                record.setdefault(field, None)
            record.setdefault("other_identifiers", {"Code Ocean": identity})
            records.append(record)
        return records

    def require_table(self, table_name: str) -> None:
        """Reject tables whose local source contracts are not implemented."""
        if table_name not in SUPPORTED_TABLES:
            raise NotImplementedError(
                f"Code Ocean does not support table {table_name!r}; supported: {sorted(SUPPORTED_TABLES)}"
            )

    def _result_path(self, table_name: str) -> Path:
        """Return a safe local Parquet path for a supported output."""
        self.require_table(table_name)
        path = self.results_root / f"{table_name}.pqt"
        if path.resolve() != path or self.data_root in path.resolve().parents:
            raise ValueError(f"Unsafe Code Ocean result path: {path}")
        return path

    def read(self, table_name: str | list[str]) -> pd.DataFrame:
        """Read only a requested local materialization, without source/network I/O."""
        if not isinstance(table_name, str):
            raise NotImplementedError("Code Ocean merged table reads are unsupported")
        self.require_table(table_name)
        if table_name in self._store:
            return self._store[table_name].copy()
        path = self._result_path(table_name)
        if table_name != "asset_basics" and path.exists():
            self._store[table_name] = pd.read_parquet(path)
            return self._store[table_name].copy()
        return pd.DataFrame()

    def write(self, table_name: str, data: pd.DataFrame) -> None:
        """Persist QC outputs separately from input assets; retain basics in memory."""
        path = self._result_path(table_name)
        if table_name != "asset_basics":
            path.parent.mkdir(parents=True, exist_ok=True)
            data.to_parquet(path, index=False)
        self._store[table_name] = data.copy()

    def cache_exists(self, table_name: str) -> bool:
        """Treat empty materialized tables as valid cache hits."""
        path = self._result_path(table_name)
        return table_name in self._store or (table_name != "asset_basics" and path.exists())

    def read_filtered(self, table_name: str, **kwargs):
        """Use the shared in-memory predicate and pagination implementation."""
        self.read(table_name)
        return super().read_filtered(table_name, **kwargs)

    def get_location(self, table_name: str, partitioned: bool = False) -> str:
        """Return the local QC Parquet location, never a public cache URI."""
        if partitioned or table_name == "asset_basics":
            raise NotImplementedError("Code Ocean has no partitioned or persisted basics location")
        return str(self._result_path(table_name))

    def _unsupported(self, *args, **kwargs):
        """Reject public-cache publication and unsupported storage operations."""
        raise NotImplementedError(
            "Code Ocean supports scoped QC tables only; registry, version and partition operations are unsupported"
        )

    put_json = _unsupported
    put_bytes = _unsupported
    get_json = _unsupported
    get_versions_index = _unsupported
    register_version = _unsupported
    put_registry_fragment = _unsupported
    list_registry_fragments = _unsupported
    clear_registry = _unsupported
    partition_exists = _unsupported
    clear_partition = _unsupported
    write_chunk = _unsupported
