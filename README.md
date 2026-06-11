# biodata-cache

[![License](https://img.shields.io/badge/license-MIT-brightgreen)](LICENSE)
![Code Style](https://img.shields.io/badge/code%20style-black-black)
[![semantic-release: angular](https://img.shields.io/badge/semantic--release-angular-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release)
![Interrogate](https://img.shields.io/badge/interrogate-37.3%25-red)
![Coverage](https://img.shields.io/badge/coverage-24%25-red)
![Python](https://img.shields.io/badge/python->=3.10,<3.14-blue?logo=python)

`biodata-cache` is a set of one-line functions that handle the entire process of caching and retrieving data (and metadata) from AIND data assets.

In the background, the cache repackages data/metadata into dataframes and stores them on S3 in versioned folders (`data-asset-cache/bdc-v{version}/`), or in memory for testing. Each release writes to its own versioned folder, so older versions of the website remain accessible while new versions are deployed. A top-level `data-asset-cache/cache_versions.json` index lists all available version folders.

Important: this package is not at 1.0. It is changing *fast* and breaking changes are still occurring, although rarely. To reduce the chance of impact on your code the cache tables are versioned. This does mean that if you want the latest version of the tables you need to keep biodata-cache up-to-date, but it also means your code won't immediately break when I change the way the tables work.

## Installation

```bash
pip install biodata-cache
```

## Usage

### Set backend

```bash
export BIODATA_CACHE_BACKEND='S3'
```

Options are 'S3', 'MEMORY'.

### Fetch data

```python
from biodata_cache import unique_project_names

project_names = unique_project_names()
```

#### Cache tables

`get_cache_registry` returns the following information about all available cache tables. Paths are versioned — `{version}` is the installed `biodata-cache` package version (e.g. `0.27.3`).

| Table | Description | Location | Type | Partitioned | Columns |
| ----- | ----------- | -------- | ---- | ----------- | ------- |
| `unique_project_names` | Unique project names across all assets | `s3://allen-data-views/data-asset-cache/bdc-v{version}/unique_project_names.pqt` | metadata | False | `project_name` |
| `unique_subject_ids` | Unique subject_ids across all assets | `s3://allen-data-views/data-asset-cache/bdc-v{version}/unique_subject_ids.pqt` | metadata | False | `subject_id` |
| `unique_genotypes` | Unique genotypes across all assets where `subject.subject_details.genotype` is present | `s3://allen-data-views/data-asset-cache/bdc-v{version}/unique_genotypes.pqt` | metadata | False | `genotype` |
| `asset_basics` | Commonly used asset metadata, one row per data asset | `s3://allen-data-views/data-asset-cache/bdc-v{version}/asset_basics.pqt` | metadata | False | `_id`, `_last_modified`, `modalities`, `project_name`, `data_level`, `subject_id`, `acquisition_start_time`, `acquisition_end_time`, `code_ocean`, `process_date`, `genotype`, `age`, `acquisition_type`, `location`, `name`, `experimenters`, `experimenters_normalized`, `instrument_id`, `instrument_id_normalized`, `investigators`, `investigators_normalized` |
| `source_data` | Mapping from derived asset names to their source raw asset names | `s3://allen-data-views/data-asset-cache/bdc-v{version}/source_data.pqt` | metadata | False | `name`, `source_data`, `pipeline_name`, `processing_time` |
| `quality_control` | Quality control table with one row per QC metric, partitioned by subject_id | `s3://allen-data-views/data-asset-cache/bdc-v{version}/qc/` | asset | True (by `subject_id`) | `name`, `stage`, `modality`, `value`, `status`, `asset_name` |
| `platform_qc` | Tag-level QC statuses aggregated per platform, one row per asset/tag combination | `s3://allen-data-views/data-asset-cache/bdc-v{version}/platform_qc/` | platform | True (by `platform`) | `asset_name`, `tag`, `status`, `timestamp`, `instrument_id_normalized`, `experimenters_normalized` |
| `assets_smartspim` | SmartSPIM assets with processing status and neuroglancer links, one row per (asset, channel) | `s3://allen-data-views/data-asset-cache/bdc-v{version}/assets_smartspim.pqt` | metadata | False | `name`, `raw_name`, `processed`, `institution`, `processing_end_time`, `stitched_link`, `raw_link`, `channel`, `segmentation_link`, `quantification_link`, `alignment_link` |
| `platform_fib` | Fiber photometry assets in long form, one row per asset/fiber/channel combination | `s3://allen-data-views/data-asset-cache/bdc-v{version}/platform_fib.pqt` | metadata | False | `asset_name`, `fiber`, `patch_cord`, `channel`, `intended_measurement`, `targeted_structure` |
| `foraging_sessions` | Foraging behavior sessions with key performance metrics, one row per session | `s3://allen-data-views/data-asset-cache/bdc-v{version}/foraging_sessions.pqt` | metadata | False | `subject_id`, `session_date`, `session`, `nwb_suffix`, `rig`, `trainer`, `trainer_normalized`, `task`, `curriculum_name`, `curriculum_version`, `current_stage_actual`, `foraging_eff`, `foraging_eff_random_seed`, `finished_trials`, `finished_rate`, `total_trials`, `bias_naive` |
| `behavior_curriculum` | Behavior assets with curriculum name and stage, one row per behavior asset | `s3://allen-data-views/data-asset-cache/bdc-v{version}/behavior_curriculum.pqt` | asset | False | `asset_name`, `curriculum_name`, `stage_name`, `stage_node_id` |

Hive-partitioned tables use `key=value` directory segments, enabling DuckDB queries like:

```python
import duckdb
duckdb.query("""
    SELECT * FROM read_parquet(
        's3://allen-data-views/data-asset-cache/bdc-v0.27.3/qc/**',
        hive_partitioning=true,
        union_by_name=true
    )
""")
```

The `cache_registry.json` registry lives at `s3://allen-data-views/data-asset-cache/bdc-v{version}/cache_registry.json`. The top-level `s3://allen-data-views/data-asset-cache/cache_versions.json` lists all available version folders as a JSON array.

The `raw_to_derived` function is not a table stored in S3, instead it is used by passing an asset_name (or list of asset names) and a modality. The function returns the latest derived asset matching the requested pattern.

### Custom cache table

The `custom` function allows you to store and retrieve your own user-defined DataFrames in the cache by name. This requires write authentication to the active backend.

```python
from biodata_cache import custom
import pandas as pd

df = pd.DataFrame({"col": [1, 2, 3]})
custom("my_data", df)

retrieved_df = custom("my_data")
```

### Update all cache tables

We run a nightly capsule on Code Ocean with this code to update all cache tables (not the custom ones).

```python
from biodata_cache.sync import update_all_tables
update_all_tables()
```
