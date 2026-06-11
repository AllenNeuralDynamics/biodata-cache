# Rename Plan: `zombie-squirrel` → `biodata-cache`

This plan renames the Python package, its distribution name, the GitHub repo
references, the S3 cache layout, and every internal symbol that uses the
squirrel / acorn / forest / tree metaphor. Backwards compatibility is **not**
preserved — `import zombie_squirrel` will stop working and the old S3 paths
will be abandoned. Each phase below is independently runnable; later phases
depend on earlier ones in the order listed.

## 0. Decisions (locked)

- **PyPI distribution name**: `biodata-cache`
- **Import package name**: `biodata_cache`
- **GitHub repo**: `AllenNeuralDynamics/biodata-cache`
- **S3 version folder**: `data-asset-cache/bdc-v{version}/`
- **S3 top-level index**: `data-asset-cache/cache_versions.json`
- **Per-version registry file**: `cache_registry.json` (was `squirrel.json`)
- **Backend env var**: `BIODATA_CACHE_BACKEND` (values: `s3`, `memory`)
- **Backwards compatibility**: none. Hard cut.

## 1. Canonical symbol & string map

Apply these renames everywhere they appear (code, tests, scripts, docs,
comments, docstrings, logging messages, decorator names, module paths,
filenames). Treat the table as authoritative — do not invent new names.

### 1.1 Distribution / package / repo

| Old | New |
| --- | --- |
| `zombie-squirrel` (PyPI / repo / prose name) | `biodata-cache` |
| `zombie_squirrel` (import package, all dotted paths) | `biodata_cache` |
| `ZOMBIE Squirrel`, `ZOMBIE squirrel` (prose) | `biodata-cache` |
| `AllenNeuralDynamics/zombie-squirrel` (URLs) | `AllenNeuralDynamics/biodata-cache` |
| `zombie-squirrel_logo.png` (file) | delete (no replacement logo) |

### 1.2 Modules / files inside the package

| Old path | New path |
| --- | --- |
| `src/zombie_squirrel/` | `src/biodata_cache/` |
| `src/zombie_squirrel/acorns.py` | `src/biodata_cache/registry.py` |
| `src/zombie_squirrel/forest.py` | `src/biodata_cache/backend.py` |
| `src/zombie_squirrel/squirrel.py` | `src/biodata_cache/models.py` |
| `src/zombie_squirrel/sync.py` | `src/biodata_cache/sync.py` (keep filename) |
| `src/zombie_squirrel/utils.py` | `src/biodata_cache/utils.py` (keep filename) |
| `src/zombie_squirrel/acorn_helpers/` | `src/biodata_cache/cache_table_helpers/` |
| `src/zombie_squirrel/acorn_helpers/*.py` | identical filenames under new folder |

The pre-existing empty stub `src/biodata_cache/cache_table_helpers/foraging/`
must be deleted as part of moving content over — the new layout has no
`foraging/` subpackage; `foraging_sessions.py` lives directly under
`cache_table_helpers/`.

### 1.3 Test paths

| Old path | New path |
| --- | --- |
| `tests/acorn_helpers/` | `tests/cache_table_helpers/` |
| `tests/test_acorns.py` | `tests/test_registry.py` |
| `tests/test_squirrel.py` | `tests/test_models.py` |
| `tests/test_trees.py` | `tests/test_backend.py` |
| `tests/test_forest_coverage.py` | `tests/test_backend_coverage.py` |
| `tests/test_sync.py` | unchanged |
| `tests/test_sync_coverage.py` | unchanged |
| `tests/test_utils.py` | unchanged |
| `tests/test_build_platform_qc.py` | unchanged |

### 1.4 Scripts

| Old path | New path |
| --- | --- |
| `scripts/hide_qc_acorn.py` | `scripts/update_qc_table.py` |
| `scripts/build_platform_qc.py` | unchanged |
| `scripts/integration_tests.py` | unchanged (rewrite docstring) |
| `scripts/normalization.py` | unchanged |
| `scripts/test_columns_integration.py` | unchanged |
| `scripts/test_qc_integration.py` | unchanged |
| `scripts/test_qc_timestamp_proof.py` | unchanged |
| `scripts/test_smartspim_integration.py` | unchanged |

### 1.5 Public symbols (classes, functions, constants, env vars)

| Old | New |
| --- | --- |
| class `Acorn` (pydantic model) | `CacheTable` |
| class `AcornType` (enum) | `CacheTableType` |
| class `Squirrel` (pydantic model) | `CacheRegistry` |
| field `Squirrel.acorns: list[Acorn]` | `CacheRegistry.tables: list[CacheTable]` |
| field `Acorn.type: AcornType` | `CacheTable.type: CacheTableType` (unchanged shape) |
| class `Tree` (abstract base) | `Backend` |
| class `S3Tree` | `S3Backend` |
| class `MemoryTree` | `MemoryBackend` |
| `Tree.hide(table_name, data)` method | `Backend.write(table_name, data)` |
| `Tree.scurry(table_name)` method | `Backend.read(table_name)` |
| `Tree._scurry_single` / `_scurry_multiple` | `_read_single` / `_read_multiple` |
| `Tree.plant(key, data)` method | `Backend.put_json(key, data)` |
| `Tree.fetch(key)` method | `Backend.get_json(key)` |
| `Tree.get_location(...)` method | unchanged name |
| module-level `TREE` (in `acorns.py`) | `BACKEND` (in `registry.py`) |
| `ACORN_REGISTRY: dict` | `TABLE_REGISTRY: dict` |
| `register_acorn(name)` decorator | `register_table(name)` |
| `NAMES` dict | unchanged name and keys/values |
| `class SquirrelMessage(BaseModel)` | `class CacheLogMessage(BaseModel)` |
| `SquirrelMessage(tree=..., acorn=..., message=...)` fields | `CacheLogMessage(backend=..., table=..., message=...)` |
| function `get_squirrel_info()` | `get_cache_registry()` |
| function `publish_squirrel_metadata()` | `publish_cache_registry()` |
| function `hide_acorns(fast, slow)` | `update_all_tables(fast, slow)` |
| function `register_acorn` (alt) | `register_table` |
| env var `FOREST_TYPE` | `BIODATA_CACHE_BACKEND` |
| env var `TREE_SPECIES` (stale, in `test_and_lint.yml` only) | `BIODATA_CACHE_BACKEND` |
| local var `forest_type` (in `acorns.py`) | `backend_type` |
| constant `ZS_VERSION` (in `utils.py`) | `BDC_VERSION` |
| constant `_CACHE_ROOT = "data-asset-cache"` | unchanged |
| constant `_VERSION_FOLDER = f"zs-v{ZS_VERSION}"` | `f"bdc-v{BDC_VERSION}"` |
| literal `"zombie-squirrels.json"` | `"cache_versions.json"` |
| literal `"squirrel.json"` | `"cache_registry.json"` |
| log field literal `tree="S3Tree"` | `backend="S3Backend"` |
| log field literal `tree="MemoryTree"` | `backend="MemoryBackend"` |
| docstring phrase "the cache" / "the squirrel" / "scurry" | "the cache" (drop metaphor) |
| comment `# --- Acorn registry and names ---` | `# --- Table registry and names ---` |

### 1.6 Docstrings / prose / log messages

Replace metaphor wording in **all** docstrings and log strings:

| Old fragment | New fragment |
| --- | --- |
| "Acorns: functions to fetch and cache data from MongoDB." | "Cache table functions that fetch and cache data from MongoDB." |
| "Storage backend interfaces for caching data." | unchanged |
| "Base class for a storage backend (the cache)." | "Base class for a cache storage backend." |
| "Initialize S3Acorn with S3 client." | "Initialize S3Backend with S3 client." |
| "Initialize MemoryAcorn with empty store." | "Initialize MemoryBackend with empty store." |
| "Store records in the cache." (abstract) | "Write records to the cache." |
| "Fetch records from the cache." | "Read records from the cache." |
| "Initializing S3 forest for caching" | "Initializing S3 backend for caching" |
| "Initializing in-memory forest for caching" | "Initializing in-memory backend for caching" |
| "Squirrel metadata container for acorns." | "Registry of cache tables." |
| "Acorn metadata definition." | "Cache table metadata definition." |
| "Enumeration of acorn data types." | "Enumeration of cache table data types." |
| "Column definition for acorn metadata." | "Column definition for a cache table." |
| "Pydantic models for Squirrel metadata." | "Pydantic models for the cache registry." |
| "Structured logging message for zombie-squirrel operations." | "Structured logging message for biodata-cache operations." |
| "Utility functions for zombie-squirrel package." | "Utility functions for the biodata-cache package." |
| "Configure logging for zombie-squirrel package." | "Configure logging for the biodata-cache package." |
| "Run the QC hide_acorn for all subjects without updating other acorns." | "Update the QC cache table for all subjects without updating other tables." |
| "Hide QC acorn for all subjects." | "Update QC cache table for all subjects." |
| "Trigger force update of registered acorn functions." | "Trigger force update of registered cache table functions." |
| "Build and publish a Squirrel metadata JSON to the cache root." | "Build and publish the cache registry JSON to the cache root." |
| "Fetch and return the Squirrel metadata from the active tree." | "Fetch and return the cache registry from the active backend." |
| "Root conftest: ensure in-memory forest is used during tests." | "Root conftest: ensure in-memory backend is used during tests." |
| variable name `qc_acorn` (in `sync.py`, `hide_qc_acorn.py`) | `qc_table_fn` |
| variable name `acorn_list` (in `sync.py`) | `table_list` |
| local arg names `tree=...` in `SquirrelMessage(...)` calls | `backend=...` |
| local arg names `acorn=...` in `SquirrelMessage(...)` calls | `table=...` |

When a docstring mentions "acorn" (lowercase noun for a cached table),
replace with "cache table". When it mentions "tree" as the storage abstraction,
replace with "backend". When it mentions "forest" as the overall storage,
replace with "backend". When it mentions "squirrel" as the registry, replace
with "cache registry". Be careful to leave domain words intact
(e.g. `foraging_sessions`, `Foraging behavior sessions`, `behavior_curriculum`,
SmartSPIM, ExaSPIM — these are real scientific terms, not metaphor).

## 2. Top-level project files

Edit each file as specified. Paths are workspace-relative.

### 2.1 [pyproject.toml](pyproject.toml)

- Change `name = "zombie-squirrel"` → `name = "biodata-cache"`.
- Change `description` from `"Generated from aind-library-template"` to
  `"Caching and synchronization for AIND metadata."`.
- Change `[tool.setuptools.dynamic] version = {attr = "zombie_squirrel.__version__"}`
  → `version = {attr = "biodata_cache.__version__"}`.
- Change `[tool.coverage.run] source = ["zombie_squirrel", "tests"]`
  → `source = ["biodata_cache", "tests"]`.
- Leave everything else (dependencies, ruff config, pytest config,
  interrogate config) unchanged.

### 2.2 [setup.py](setup.py)

- Update docstring from `"""Setup configuration for zombie-squirrel package."""`
  to `"""Setup configuration for biodata-cache package."""`.

### 2.3 [conftest.py](conftest.py)

- Replace contents with:

  ```python
  """Root conftest: ensure in-memory backend is used during tests."""

  import os

  os.environ["BIODATA_CACHE_BACKEND"] = "memory"
  ```

### 2.4 [CITATION.cff](CITATION.cff)

- `title: "zombie-squirrel"` → `title: "biodata-cache"`.
- `url: "https://github.com/AllenNeuralDynamics/zombie-squirrel"` →
  `url: "https://github.com/AllenNeuralDynamics/biodata-cache"`.
- Keep `version` and `date-release` as-is (release workflow will bump them).

### 2.5 [README.md](README.md)

Apply all string substitutions from §1. Specific replacements required:

- Title `# ZOMBIE Squirrel` → `# biodata-cache`.
- Delete the `<img src="zombie-squirrel_logo.png" ...>` line entirely
  (the asset is being removed).
- All prose mentions of `zombie-squirrel` / `ZOMBIE squirrel` → `biodata-cache`.
- `pip install zombie-squirrel` → `pip install biodata-cache`.
- `export FOREST_TYPE='S3'` → `export BIODATA_CACHE_BACKEND='S3'`.
- `from zombie_squirrel import ...` → `from biodata_cache import ...`
  (applies to every code block).
- `from zombie_squirrel.sync import hide_acorns` → `from biodata_cache.sync import update_all_tables`.
- `hide_acorns()` → `update_all_tables()`.
- `get_squirrel_info` (prose & code) → `get_cache_registry`.
- Heading `#### Acorns` → `#### Cache tables`.
- Heading `### Custom acorn` → `### Custom cache table`.
- Heading `### Hide all the acorns` → `### Update all cache tables`.
- Heading `### Scurry (fetch) data` → `### Fetch data`.
- Column header `| Acorn |` in the table → `| Table |`.
- S3 path fragments `data-asset-cache/zs-v{version}/` → `data-asset-cache/bdc-v{version}/`.
- S3 path fragments `data-asset-cache/zs-v0.27.3/` → `data-asset-cache/bdc-v0.27.3/` (example).
- `zombie-squirrels.json` → `cache_versions.json`.
- `squirrel.json` → `cache_registry.json`.
- Sentence "Hive-partitioned acorns use…" → "Hive-partitioned tables use…".
- Sentence "The squirrel.json registry lives at…" rewrite to reference
  `cache_registry.json` and `cache_versions.json`.
- Sentence containing "to keep zombie-squirrel up-to-date" →
  "to keep biodata-cache up-to-date".
- Leave the badge image URLs and the python/coverage/interrogate badges
  alone; the publish workflow regenerates them.

### 2.6 [run_tests.py](run_tests.py)

- No content changes required. Verify it still runs `pytest tests`.

### 2.7 [CONTRIBUTING.md](CONTRIBUTING.md)

- No package-name references currently present. No changes required.
  Confirm with grep before declaring done.

### 2.8 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), [LICENSE](LICENSE)

- No changes required. Confirm with grep.

### 2.9 [.github/workflows/test_and_lint.yml](.github/workflows/test_and_lint.yml)

- Replace `export TREE_SPECIES=memory` with
  `export BIODATA_CACHE_BACKEND=memory`.

### 2.10 [.github/workflows/tag_and_publish.yml](.github/workflows/tag_and_publish.yml)

- No direct package-name references in the YAML keys. The publish step uses
  `python -m build` and reads `pyproject.toml`, so updating
  `pyproject.toml` (§2.1) is sufficient.
- Confirm `coverage run -m unittest discover` still produces a coverage
  number after the rename (no changes needed unless the source path
  changed; `[tool.coverage.run] source` covers it).

### 2.11 [.github/copilot-instructions.md](.github/copilot-instructions.md)

- No content changes required (no package references).

### 2.12 [.github/dependabot.yml](.github/dependabot.yml), [.github/ISSUE_TEMPLATE/](.github/ISSUE_TEMPLATE)

- No expected references. Grep to confirm, edit if any are found.

### 2.13 [.pre-commit-config.yaml](.pre-commit-config.yaml)

- No references. No changes.

### 2.14 [.vscode/settings.json](.vscode/settings.json)

- No references. No changes.

### 2.15 Logo and generated artifacts

- Delete `zombie-squirrel_logo.png`.
- Delete the entire `htmlcov/` directory and `coverage.json`; they are
  regenerated by `coverage run`.
- Delete `.coverage` if present.
- Delete every `__pycache__/` directory under `src/`, `tests/`, `scripts/`,
  and the repo root.
- Leave `tests/resources/` contents untouched (they are test fixtures, not
  Python modules).
- Leave `temp-swdb/` (currently empty) untouched.

## 3. Source code rewrite (`src/zombie_squirrel/` → `src/biodata_cache/`)

### 3.1 Move and rename modules

1. Delete the existing empty `src/biodata_cache/cache_table_helpers/foraging/`
   subtree (it is a stale stub).
2. Move every file from `src/zombie_squirrel/` to `src/biodata_cache/`,
   renaming according to §1.2:
   - `acorns.py` → `registry.py`
   - `forest.py` → `backend.py`
   - `squirrel.py` → `models.py`
   - `sync.py`, `utils.py`, `__init__.py` → keep filename
   - `acorn_helpers/` → `cache_table_helpers/` (preserve all 14 helper
     module filenames including `__init__.py`)
3. After moving, delete the now-empty `src/zombie_squirrel/` directory.

### 3.2 Per-module edits

For every moved `.py` file, perform:

- Replace every `zombie_squirrel` dotted import with `biodata_cache`.
- Replace `acorn_helpers` in imports with `cache_table_helpers`.
- Replace `from zombie_squirrel.acorns import ...` with
  `from biodata_cache.registry import ...`.
- Replace `from zombie_squirrel.forest import ...` with
  `from biodata_cache.backend import ...`.
- Replace `from zombie_squirrel.squirrel import ...` with
  `from biodata_cache.models import ...`.
- Replace `from .acorns import ...` with `from .registry import ...`.
- Replace `from .acorn_helpers.X import ...` with
  `from .cache_table_helpers.X import ...`.
- Replace `from .squirrel import ...` with `from .models import ...`.
- Apply every symbol rename from §1.5 (class names, function names,
  decorator names, env var names, constant names).
- Apply every docstring / log message change from §1.6.

#### 3.2.1 [src/biodata_cache/__init__.py](src/biodata_cache/__init__.py) (was `src/zombie_squirrel/__init__.py`)

Final contents must be exactly:

```python
"""biodata-cache: caching and synchronization for AIND metadata.

Provides functions to fetch and cache project names, subject IDs, and asset
metadata from the AIND metadata database with support for multiple backends.
Also exposes get_cache_registry to retrieve the registry of all available
cache tables and their metadata.
"""

__version__ = "0.30.1"

from biodata_cache.cache_table_helpers.asset_basics import asset_basics  # noqa: F401
from biodata_cache.cache_table_helpers.foraging_sessions import foraging_sessions  # noqa: F401
from biodata_cache.cache_table_helpers.platform_smartspim import assets_smartspim  # noqa: F401
from biodata_cache.cache_table_helpers.platform_exaspim import platform_exaspim  # noqa: F401
from biodata_cache.cache_table_helpers.behavior_curriculum import behavior_curriculum  # noqa: F401
from biodata_cache.cache_table_helpers.platform_fib import platform_fib  # noqa: F401
from biodata_cache.cache_table_helpers.platform_qc import platform_qc  # noqa: F401
from biodata_cache.cache_table_helpers.custom import custom  # noqa: F401
from biodata_cache.cache_table_helpers.metadata_upgrade import metadata_upgrade  # noqa: F401
from biodata_cache.cache_table_helpers.qc import qc, qc_columns  # noqa: F401
from biodata_cache.cache_table_helpers.raw_to_derived import raw_to_derived  # noqa: F401
from biodata_cache.cache_table_helpers.source_data import source_data  # noqa: F401
from biodata_cache.cache_table_helpers.unique_project_names import (  # noqa: F401
    unique_project_names,
)
from biodata_cache.cache_table_helpers.unique_genotypes import (  # noqa: F401
    unique_genotypes,
)
from biodata_cache.cache_table_helpers.unique_subject_ids import (  # noqa: F401
    unique_subject_ids,
)
from biodata_cache.utils import get_cache_registry  # noqa: F401
```

Preserve the existing `__version__` value verbatim.

#### 3.2.2 [src/biodata_cache/registry.py](src/biodata_cache/registry.py) (was `acorns.py`)

- Module docstring: `"""Cache table registry: functions to fetch and cache data from MongoDB."""`.
- `from zombie_squirrel.forest import MemoryTree, S3Tree` →
  `from biodata_cache.backend import MemoryBackend, S3Backend`.
- `from zombie_squirrel.utils import SquirrelMessage` →
  `from biodata_cache.utils import CacheLogMessage`.
- Env var: `os.getenv("FOREST_TYPE", "memory")` → `os.getenv("BIODATA_CACHE_BACKEND", "memory")`.
- Local `forest_type` → `backend_type`.
- Error message: `f"Unknown FOREST_TYPE: {forest_type}"` →
  `f"Unknown BIODATA_CACHE_BACKEND: {backend_type}"`.
- `TREE = S3Tree()` → `BACKEND = S3Backend()`; `TREE = MemoryTree()` → `BACKEND = MemoryBackend()`.
- Section comment `# --- Acorn registry and names ---` → `# --- Cache table registry and names ---`.
- `ACORN_REGISTRY` → `TABLE_REGISTRY`.
- `def register_acorn(name)` → `def register_table(name)`. Inner docstrings
  updated to `"""Register cache table function with registry."""` and
  `"""Register function in cache table registry."""`.
- All `SquirrelMessage(tree=..., acorn=...)` constructor calls →
  `CacheLogMessage(backend=..., table=...)`.
- The `NAMES` dict (keys and values) is **unchanged**.

#### 3.2.3 [src/biodata_cache/backend.py](src/biodata_cache/backend.py) (was `forest.py`)

- Module docstring unchanged in meaning ("Storage backend interfaces for caching data.").
- `from zombie_squirrel.utils import SquirrelMessage, ZS_VERSION` →
  `from biodata_cache.utils import CacheLogMessage, BDC_VERSION`.
- `_VERSION_FOLDER = f"zs-v{ZS_VERSION}"` → `_VERSION_FOLDER = f"bdc-v{BDC_VERSION}"`.
- `class Tree(ABC)` → `class Backend(ABC)`. Docstring "Base class for a
  cache storage backend.".
- `class S3Tree(Tree)` → `class S3Backend(Backend)`.
- `class MemoryTree(Tree)` → `class MemoryBackend(Backend)`.
- Methods on every subclass:
  - `hide(self, table_name, data)` → `write(self, table_name, data)`. Docstring
    "Write DataFrame to the cache.".
  - `scurry(self, table_name)` → `read(self, table_name)`. Docstring
    "Read DataFrame from the cache.".
  - `_scurry_single` → `_read_single`; `_scurry_multiple` → `_read_multiple`.
  - `plant(self, key, data)` → `put_json(self, key, data)`.
  - `fetch(self, key)` → `get_json(self, key)`.
  - `get_location(...)` keeps its name.
- All log calls: `SquirrelMessage(tree="S3Tree", acorn=..., message=...)`
  → `CacheLogMessage(backend="S3Backend", table=..., message=...)`, and
  likewise `tree="MemoryTree"` → `backend="MemoryBackend"`,
  `acorn="merged"` → `table="merged"`,
  `acorn="system"` → `table="system"`.
- S3 literal `index_key = f"{_CACHE_ROOT}/zombie-squirrels.json"`
  → `index_key = f"{_CACHE_ROOT}/cache_versions.json"`.
- Memory store literals `self._json_store.get("zombie-squirrels.json", "[]")`
  → `self._json_store.get("cache_versions.json", "[]")`; and
  `self._json_store["zombie-squirrels.json"] = json.dumps(existing)` →
  `self._json_store["cache_versions.json"] = json.dumps(existing)`.
- Init docstrings:
  - `S3Backend.__init__`: `"""Initialize S3Backend with S3 client."""`.
  - `MemoryBackend.__init__`: `"""Initialize MemoryBackend with empty store."""`.
- `HIVE_PARTITION_KEYS` dict: unchanged keys and values.

#### 3.2.4 [src/biodata_cache/models.py](src/biodata_cache/models.py) (was `squirrel.py`)

Final contents must be:

```python
"""Pydantic models for the cache registry."""

from enum import Enum

from pydantic import BaseModel


class CacheTableType(str, Enum):
    """Enumeration of cache table data types."""

    metadata = "metadata"
    asset = "asset"
    event = "event"
    realtime = "realtime"
    platform = "platform"


class Column(BaseModel):
    """Column definition for a cache table."""

    name: str
    description: str


class CacheTable(BaseModel):
    """Cache table metadata definition."""

    name: str
    description: str
    location: str
    partitioned: bool
    partition_key: str | None = None
    type: CacheTableType
    columns: list[Column] = []


class CacheRegistry(BaseModel):
    """Registry of cache tables."""

    tables: list[CacheTable]
```

Note: the JSON field name changes from `acorns` to `tables`. This is a
breaking wire-format change — confirmed acceptable because the S3 layout
is also moving and no old consumers should be reading the new path.

#### 3.2.5 [src/biodata_cache/sync.py](src/biodata_cache/sync.py) (was `sync.py`)

- Imports: rewrite all `.acorn_helpers.X` → `.cache_table_helpers.X`.
- `from .acorns import ACORN_REGISTRY, NAMES, TREE` →
  `from .registry import TABLE_REGISTRY, NAMES, BACKEND`.
- `from .squirrel import Acorn, AcornType, Squirrel` →
  `from .models import CacheTable, CacheTableType, CacheRegistry`.
- `def publish_squirrel_metadata()` → `def publish_cache_registry()`,
  with docstring: `"""Build and publish the cache registry JSON to the cache root."""`.
- Inside the function: `acorn_list = [Acorn(... type=AcornType.metadata, ...)]`
  → `table_list = [CacheTable(... type=CacheTableType.metadata, ...)]`, etc.,
  for every entry. Preserve every `name`, `description`, `location`,
  `partitioned`, `partition_key`, `type`, and `columns=` value as-is —
  only the class names change.
- `TREE.get_location(...)` → `BACKEND.get_location(...)` everywhere.
- `squirrel = Squirrel(acorns=acorn_list)` →
  `registry = CacheRegistry(tables=table_list)`.
- `TREE.plant("squirrel.json", squirrel.model_dump_json())` →
  `BACKEND.put_json("cache_registry.json", registry.model_dump_json())`.
- `def hide_acorns(fast=True, slow=True)` → `def update_all_tables(fast=True, slow=True)`.
- Docstring updated per §1.6.
- Inside the function: `ACORN_REGISTRY` → `TABLE_REGISTRY`; `qc_acorn` →
  `qc_table_fn`; trailing call `publish_squirrel_metadata()` →
  `publish_cache_registry()`.

#### 3.2.6 [src/biodata_cache/utils.py](src/biodata_cache/utils.py) (was `utils.py`)

- Module docstring: `"""Utility functions for the biodata-cache package."""`.
- `from zombie_squirrel import __version__ as ZS_VERSION` →
  `from biodata_cache import __version__ as BDC_VERSION`.
- `class SquirrelMessage(BaseModel)` → `class CacheLogMessage(BaseModel)`.
  Docstring: `"""Structured logging message for biodata-cache operations."""`.
  Field renames: `tree: str` → `backend: str`; `acorn: str` → `table: str`.
  `message: str` unchanged. `to_json` unchanged.
- `def setup_logging()` docstring: `"""Configure logging for the biodata-cache package."""`.
- `def get_squirrel_info()` → `def get_cache_registry()`. Docstring:
  `"""Fetch and return the cache registry from the active backend."""`.
  Body:

  ```python
  import biodata_cache.registry as registry
  from biodata_cache.models import CacheRegistry

  data = registry.BACKEND.get_json("cache_registry.json")
  return CacheRegistry.model_validate_json(data)
  ```

- All other utility functions (`normalize_instrument_id`, `normalize_name`,
  `_merge_key`, `_resolve_first_names`, `parse_experimenters`,
  `build_first_name_map`, `apply_first_name_map`, `normalize_experimenters`,
  and the `_INSTRUMENT_ID_RE` regex) are **unchanged**.

#### 3.2.7 `src/biodata_cache/cache_table_helpers/*.py` (14 files)

For every helper module (`asset_basics.py`, `behavior_curriculum.py`,
`custom.py`, `foraging_sessions.py`, `metadata_core.py`,
`metadata_upgrade.py`, `platform_exaspim.py`, `platform_fib.py`,
`platform_qc.py`, `platform_smartspim.py`, `qc.py`, `raw_to_derived.py`,
`source_data.py`, `unique_genotypes.py`, `unique_project_names.py`,
`unique_subject_ids.py`, and `__init__.py`):

- Replace any `from zombie_squirrel...` import with the `biodata_cache`
  equivalent (using §1.2 path map).
- Replace `from zombie_squirrel.acorns import ...` with
  `from biodata_cache.registry import ...` (and rename
  `TREE`→`BACKEND`, `ACORN_REGISTRY`→`TABLE_REGISTRY`,
  `register_acorn`→`register_table`).
- Replace `from zombie_squirrel.utils import SquirrelMessage` with
  `from biodata_cache.utils import CacheLogMessage`.
- Replace any usage of decorator `@register_acorn(...)` with `@register_table(...)`.
- Replace any direct call to `TREE.hide/scurry/plant/fetch` with
  `BACKEND.write/read/put_json/get_json` respectively.
- Replace `SquirrelMessage(tree=..., acorn=...)` calls with
  `CacheLogMessage(backend=..., table=...)`.
- Update any docstring "acorn" → "cache table" (lowercase noun usage).

After editing, verify per-file with:

```bash
grep -rE "zombie_squirrel|acorn_helpers|SquirrelMessage|FOREST_TYPE|\bTREE\b|\bAcorn\b|\bSquirrel\b|\bscurry\b|\bhide_acorns\b|\bplant\b|\bregister_acorn\b|ACORN_REGISTRY|squirrel\.json|zombie-squirrels\.json|zs-v" src/biodata_cache
```

The expected result is zero matches.

## 4. Tests rewrite (`tests/`)

### 4.1 Move and rename

- Rename `tests/acorn_helpers/` → `tests/cache_table_helpers/`.
- Rename test files per §1.3.
- Inside `tests/cache_table_helpers/__init__.py` update the docstring from
  `"""Init file for acorns test module."""` to
  `"""Init file for cache table helpers test module."""`.
- Inside `tests/__init__.py` update the docstring from
  `"""Unit tests for zombie-squirrel package."""` to
  `"""Unit tests for biodata-cache package."""`.

### 4.2 Per-test edits

For every `tests/**/*.py`:

- `import zombie_squirrel...` → `import biodata_cache...`.
- `from zombie_squirrel...` → `from biodata_cache...`.
- `acorn_helpers` → `cache_table_helpers` in every dotted path.
- `@patch("zombie_squirrel.acorn_helpers.X.acorns.TREE")` →
  `@patch("biodata_cache.cache_table_helpers.X.registry.BACKEND")`.
- `@patch("zombie_squirrel.acorn_helpers.X.MetadataDbClient")` →
  `@patch("biodata_cache.cache_table_helpers.X.MetadataDbClient")`.
- `@patch("zombie_squirrel.sync.publish_squirrel_metadata")` →
  `@patch("biodata_cache.sync.publish_cache_registry")`.
- `@patch("zombie_squirrel.sync.ACORN_REGISTRY")` →
  `@patch("biodata_cache.sync.TABLE_REGISTRY")`.
- `from zombie_squirrel.sync import hide_acorns` →
  `from biodata_cache.sync import update_all_tables`. Update every call
  `hide_acorns(...)` → `update_all_tables(...)`. Update test function name
  `test_hide_acorns_fallback_sequential_on_concurrent_failure` →
  `test_update_all_tables_fallback_sequential_on_concurrent_failure`.
- `from zombie_squirrel.forest import MemoryTree` →
  `from biodata_cache.backend import MemoryBackend`.
- `import zombie_squirrel.acorns as acorns` →
  `import biodata_cache.registry as registry`. Update every subsequent
  reference: `acorns.TREE` → `registry.BACKEND`,
  `acorns.TREE = MemoryTree()` → `registry.BACKEND = MemoryBackend()`,
  `acorns.TREE.hide("qc/...", ...)` → `registry.BACKEND.write("qc/...", ...)`.
- `mock_tree.scurry.return_value = ...` → `mock_backend.read.return_value = ...`
  (rename local fixture name `mock_tree` → `mock_backend` for clarity).
- `acorn.bucket` (in `test_trees.py` → `test_backend.py`) → `backend.bucket`
  (rename local variable).
- S3 key string assertions referencing `data-asset-cache/{_VF}/...` remain
  correct because `_VF` is `_VERSION_FOLDER` which now equals
  `bdc-v{BDC_VERSION}`. Update the import of `_VF` to reflect the new
  module: `from biodata_cache.backend import _VERSION_FOLDER as _VF`
  (replacing the old `from zombie_squirrel.forest import _VERSION_FOLDER as _VF`).
- Any test asserting on the literal `zs-v` prefix must be updated to `bdc-v`.
- Any test asserting on `zombie-squirrels.json` must be updated to
  `cache_versions.json`.
- Any test asserting on `squirrel.json` must be updated to `cache_registry.json`.
- Any test asserting on `SquirrelMessage` fields must use `CacheLogMessage`
  with `backend` / `table` field names.
- Update any test referencing `Acorn` / `AcornType` / `Squirrel` classes to
  `CacheTable` / `CacheTableType` / `CacheRegistry`. The `Squirrel(acorns=...)`
  kwarg becomes `CacheRegistry(tables=...)`.
- Update any test referencing `register_acorn` / `ACORN_REGISTRY` to use
  the new names.

### 4.3 `tests/resources/`

- Leave fixture file contents untouched **unless** they are JSON or YAML
  containing string literals like `zombie-squirrel`, `squirrel.json`,
  `zombie-squirrels.json`, or `zs-v`. Grep first; if matches exist,
  update them and document each change in the commit message.

## 5. Scripts rewrite (`scripts/`)

For every file in `scripts/`:

- `from zombie_squirrel...` → `from biodata_cache...`.
- `import zombie_squirrel...` → `import biodata_cache...`.
- `acorn_helpers` → `cache_table_helpers` in dotted paths.
- `os.environ["FOREST_TYPE"] = "s3"` → `os.environ["BIODATA_CACHE_BACKEND"] = "s3"`.
- `os.environ["FOREST_TYPE"] = "memory"` → `os.environ["BIODATA_CACHE_BACKEND"] = "memory"`.
- `from zombie_squirrel.acorns import TREE` →
  `from biodata_cache.registry import BACKEND`. Update `TREE.get_location(...)`
  → `BACKEND.get_location(...)`.
- `from zombie_squirrel.acorns import ACORN_REGISTRY, NAMES` →
  `from biodata_cache.registry import TABLE_REGISTRY, NAMES`. Update every
  `ACORN_REGISTRY` reference → `TABLE_REGISTRY`.
- `from zombie_squirrel.acorn_helpers.platform_qc import PLATFORMS` →
  `from biodata_cache.cache_table_helpers.platform_qc import PLATFORMS`.

### 5.1 Specific script files

#### [scripts/hide_qc_acorn.py](scripts/hide_qc_acorn.py)

- Rename file to `scripts/update_qc_table.py`.
- Module docstring: `"""Update the QC cache table for all subjects without updating other tables."""`.
- `def main()` docstring: `"""Update QC cache table for all subjects."""`.
- Rename local `qc_acorn` → `qc_table_fn` everywhere.
- Rename helper `_check_subject_needs_update(subject_id, qc_acorn)` parameter
  to `qc_table_fn`.
- Replace `ACORN_REGISTRY` with `TABLE_REGISTRY` (already covered).

#### [scripts/integration_tests.py](scripts/integration_tests.py)

- Module docstring lines 1–4: replace `zombie-squirrel` with `biodata-cache`
  and replace `squirrel functions` with `cache table functions`.

#### [scripts/test_qc_timestamp_proof.py](scripts/test_qc_timestamp_proof.py)

- Update `os.environ["FOREST_TYPE"] = "s3"` per §5 rule.
- Update imports per §5 rules.

#### [scripts/test_qc_integration.py](scripts/test_qc_integration.py)

- `QC_PREFIX = "data-asset-cache/zs_qc/"` — verify whether this path is
  actually `zs-v...qc/` from the production layout. **Do not** assume it
  is metaphor-driven; check git history / current S3 contents before
  changing. If unchanged production data lives here, leave as-is and
  add a `# pragma: hardcoded legacy prefix` comment.
  Default action: leave unchanged unless the user explicitly asks.

#### [scripts/build_platform_qc.py](scripts/build_platform_qc.py), [scripts/test_smartspim_integration.py](scripts/test_smartspim_integration.py), [scripts/test_columns_integration.py](scripts/test_columns_integration.py), [scripts/normalization.py](scripts/normalization.py)

- Apply only the §5 generic substitutions. No other content changes.

## 6. Order of operations

Run phases sequentially. Within a phase, files can be edited in parallel.

1. **Phase A — Configuration** (§2.1, §2.2, §2.3, §2.4, §2.9): update
   `pyproject.toml`, `setup.py`, `conftest.py`, `CITATION.cff`,
   `test_and_lint.yml`. Do not run tests yet — the source still imports
   `zombie_squirrel`.
2. **Phase B — Source move** (§3.1): move files, rename modules, delete
   the empty `src/zombie_squirrel/` and the stub `cache_table_helpers/foraging/`.
3. **Phase C — Source rewrite** (§3.2): edit every module under
   `src/biodata_cache/` to use new names.
4. **Phase D — Tests move + rewrite** (§4).
5. **Phase E — Scripts rewrite** (§5).
6. **Phase F — Docs and cleanup** (§2.5 README, §2.15 cleanup of `htmlcov/`,
   `coverage.json`, `.coverage`, `__pycache__/`, logo file).
7. **Phase G — Verification** (§7).
8. **Phase H — Reinstall** (§8).

## 7. Verification

After Phase F, run these checks. All must pass.

### 7.1 Grep audits (all must produce **zero** matches outside this PLAN.md)

```bash
grep -rnE "zombie[-_]squirrel|zombie-squirrels" --include='*.py' --include='*.md' --include='*.toml' --include='*.yml' --include='*.yaml' --include='*.cff' .
grep -rnE "\bacorn\b|\bacorns\b|\bAcorn\b|\bAcornType\b|\bACORN_REGISTRY\b|register_acorn|acorn_helpers" --include='*.py' --include='*.md' .
grep -rnE "\bSquirrel\b|\bSquirrelMessage\b|\bsquirrel\.json\b|get_squirrel_info|publish_squirrel_metadata" --include='*.py' --include='*.md' .
grep -rnE "\bforest\b|\bForest\b|FOREST_TYPE|TREE_SPECIES|\bTree\b|S3Tree|MemoryTree|\bTREE\b" --include='*.py' --include='*.md' --include='*.yml' .
grep -rnE "\bscurry\b|\bplant\b|\bhide_acorns\b|hide_qc_acorn" --include='*.py' --include='*.md' .
grep -rnE "zs-v|ZS_VERSION" --include='*.py' --include='*.md' .
```

Exception: if `scripts/test_qc_integration.py` retains its legacy
`zs_qc/` literal (see §5.1), document that and exclude that line via
`grep -v`.

The string `forest` appears nowhere in the new code. The string `tree`
appears nowhere except inside scientific identifiers (none in this repo
— verify).

### 7.2 Static checks

```bash
. .venv/bin/activate
ruff check .
ruff format --check .
interrogate --verbose .
```

All three must exit 0.

### 7.3 Tests

```bash
. .venv/bin/activate
BIODATA_CACHE_BACKEND=memory python -m unittest discover -s tests -v
BIODATA_CACHE_BACKEND=memory coverage run -m unittest discover -s tests
coverage report
```

Coverage threshold is `fail_under = 100` per `pyproject.toml`; this is the
project's existing target, not a new requirement.

### 7.4 Build

```bash
. .venv/bin/activate
python -m build
twine check dist/*
```

The built artifacts must be named `biodata_cache-<version>-py3-none-any.whl`
and `biodata-cache-<version>.tar.gz`.

## 8. Reinstall

After all checks pass:

```bash
. .venv/bin/activate
pip uninstall -y zombie-squirrel biodata-cache
pip install -e . --group dev
python -c "import biodata_cache; print(biodata_cache.__version__)"
python -c "from biodata_cache import unique_project_names, get_cache_registry; print('ok')"
```

The first command tolerates either being absent. The two import smoke
tests must print without error.

## 9. Out of scope (do **not** do as part of this rename)

- Do **not** bump `__version__`. Release tooling will do that on the next
  semantic-release run.
- Do **not** migrate any S3 data from `data-asset-cache/zs-v*` to
  `data-asset-cache/bdc-v*`. That is a separate operations task; this PR
  only changes what the code writes to next.
- Do **not** publish to PyPI manually. `tag_and_publish.yml` handles it.
- Do **not** add a deprecation shim, dual-publish, or back-compat alias.
- Do **not** modify any logic, signature semantics, dependency versions,
  ruff rules, interrogate configuration, or test assertions beyond what
  this plan explicitly requires.
- Do **not** rewrite or "improve" docstrings beyond the mappings in §1.6.
- Do **not** add comments explaining the rename.
- Do **not** modify `tests/resources/` fixture files unless §4.3 applies.
- Do **not** rename the GitHub repo via API or update remote URLs in
  `.git/config`; the repo rename is performed by a human admin separately.
  Only update string references inside tracked files.

## 10. Single-file checklist (for the executing agent)

Mark each item as you go.

- [ ] `pyproject.toml` updated (name, description, version attr, coverage source).
- [ ] `setup.py` docstring updated.
- [ ] `conftest.py` env var renamed.
- [ ] `CITATION.cff` title + url updated.
- [ ] `.github/workflows/test_and_lint.yml` env var renamed.
- [ ] `src/zombie_squirrel/` files moved to `src/biodata_cache/` with renames per §1.2.
- [ ] `src/zombie_squirrel/` directory deleted.
- [ ] `src/biodata_cache/cache_table_helpers/foraging/` stub deleted.
- [ ] `src/biodata_cache/__init__.py` matches the canonical block in §3.2.1.
- [ ] `src/biodata_cache/registry.py` edited per §3.2.2.
- [ ] `src/biodata_cache/backend.py` edited per §3.2.3.
- [ ] `src/biodata_cache/models.py` matches the canonical block in §3.2.4.
- [ ] `src/biodata_cache/sync.py` edited per §3.2.5.
- [ ] `src/biodata_cache/utils.py` edited per §3.2.6.
- [ ] All 16 files under `src/biodata_cache/cache_table_helpers/` edited per §3.2.7.
- [ ] All test files moved + edited per §4.
- [ ] All script files edited per §5; `hide_qc_acorn.py` renamed to `update_qc_table.py`.
- [ ] `README.md` edited per §2.5.
- [ ] `zombie-squirrel_logo.png` deleted.
- [ ] `htmlcov/`, `coverage.json`, `.coverage`, all `__pycache__/` deleted.
- [ ] All grep audits in §7.1 return zero matches.
- [ ] `ruff check`, `ruff format --check`, `interrogate --verbose .` all pass.
- [ ] Tests pass with 100% coverage.
- [ ] `python -m build && twine check dist/*` succeeds and produces
      `biodata_cache-*.whl`.
- [ ] Editable reinstall + smoke imports succeed.
