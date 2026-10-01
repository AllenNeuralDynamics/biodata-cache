---
name: record-consistency
description: Add or change record-consistency checks and sources in biodata-cache, or change the record_consistency_results and record_consistency_checks tables. Use when asked to add a consistency check (duplicates, missing counterparts, S3 vs DocDB coverage, per-record validation), add a record source, change how unchanged records are skipped, or when working in src/biodata_cache/cache_table_helpers/record_consistency/.
---

# Record-consistency checks

## What the tables are

The `record_consistency_checks` sync job writes one snapshot of live consistency
state as two tables:

- `record_consistency_results` — one row per evaluated record per check: whether
  that record currently passes that check.
- `record_consistency_checks` — one row per check: its description, source link,
  hash, counts, and timings for the run.

Neither keeps history. Both carry the same `checked_at`, so consumers (the Zombie
`/record-consistency` page) can tell whether they come from the same run.

The code lives in `src/biodata_cache/cache_table_helpers/record_consistency/`:

- `framework.py` — `Source` and `Check` base classes, their registries, reuse of
  unchanged results, the snapshot builder, and both tables' column definitions.
- `sources.py` — record sources.
- `checks/` — one module per check.

## Concepts

| Term | Meaning |
|---|---|
| Check | A subclass of `Check` that returns `pass`, `fail`, or `None` (skipped) for each record of one source. Pure: no I/O. |
| Check key | The check module's filename, e.g. `docdb_duplicate_name_v2`. The single identifier for the check in both tables, the page, and reuse. |
| Check hash | First 12 hex characters of the SHA-256 of the check module's source. Changes whenever the module changes; gates reuse. |
| Check description | The check class's `description` string literal, shown on the page. Starts with "Fails". |
| Check source URL | Link to the check class in the tagged biodata-cache release that produced the snapshot. |
| Source | A subclass of `Source` that loads one population of records, once per run, for every check that uses it. Owns all I/O. |
| Record kind | What a source's records are (`docdb_v2`, `s3_prefix`); tells consumers how to link a row. |
| Record ID | The record's identifier in its source system: a DocDB `_id`, or an S3 URI. |
| Record last modified | The record's last-modified timestamp in its source system when it was checked; null when the source has none. |
| Extra fields | Source fields beyond the stored record fields, such as `code_ocean_ids` on `docdb_v2`, that checks read but the results table does not store. |
| Skipped record | A record a check returned `None` for because it cannot judge it, for example a v2 record with no visible Code Ocean data asset. It has no result row and is counted in `skipped_count`. |
| `compares_across_records` | True when a record's result can change because a *different* record changed (duplicate names, missing counterparts). Such results are never reused. |
| Reuse | Carrying a previous result forward without re-evaluating it. Only for checks that do not compare across records, and only when record ID and record last modified match the previous results and the check hash matches the previous checks table. |
| Snapshot | One complete run's output, which replaces the previous one. |
| Cold run | A run with no usable previous snapshot (first run, new cache version folder, changed columns, or `force_full_rerun`); evaluates everything. |

## Table columns

`record_consistency_results`, sorted by `(check_key, name, record_id)`:

| Column | Value |
|---|---|
| `check_key` | Check module filename; joins `record_consistency_checks` |
| `status` | `pass` or `fail` |
| `record_kind` | From the source |
| `record_id` | DocDB `_id` or S3 URI |
| `name` | Record name |
| `location` | Record S3 location, when known |
| `record_last_modified` | Source last-modified timestamp, nullable |
| `checked_at` | Snapshot time, identical on every row |

`record_consistency_checks`, sorted by `check_key`:

| Column | Value |
|---|---|
| `check_key` | Check module filename |
| `check_description` | The check's `description` |
| `check_source_url` | Link to the check at the release that ran |
| `check_hash` | Hash of the check module's source; gates reuse on the next run |
| `source` | The source whose records the check evaluated |
| `evaluated_count` | Records with a result, evaluated or reused |
| `failed_count` | Records that failed |
| `reused_count` | Results carried over without re-evaluation |
| `skipped_count` | Records the check returned `None` for; no result row |
| `check_eval_seconds` | Seconds spent in `evaluate()` |
| `source_load_seconds` | Seconds spent loading the source; shared by checks that read it |
| `checked_at` | Snapshot time, equal to the results' `checked_at` |

Zombie builds SQL from these names; change a column only together with the
Zombie page.

## Adding a check

Add one module under `checks/`, import it in `checks/__init__.py`, and add its
logic tests to `tests/cache_table_helpers/record_consistency/test_checks.py`.

```python
"""Duplicate record names within DocDB v2."""

from collections import Counter
from typing import Any

from biodata_cache.cache_table_helpers.record_consistency.framework import FAIL, PASS, Check


class DuplicateNameV2(Check):
    """Fail v2 records that share an exact name with another v2 record."""

    description = (
        "Fails DocDB v2 records whose 'name' field exactly matches the 'name' field of another DocDB v2 record."
    )
    source = "docdb_v2"
    compares_across_records = True

    def evaluate(self, records: list[dict[str, Any]], **needed: list[dict[str, Any]]) -> list[str]:
        """Fail each record whose name appears more than once."""
        counts = Counter(record["name"] for record in records)
        return [FAIL if counts[record["name"]] > 1 else PASS for record in records]
```

Rules:

- The module filename is the check key and must be snake_case. Renaming the
  module creates a new check with no reuse; do it deliberately.
- `description` is a non-empty string literal; the docstring is for developers.
- `source` names the records the check evaluates. `needs` names other sources it
  compares against; they arrive as keyword arguments named after the source.
- `evaluate` returns one `pass`, `fail`, or `None` per input record, in input
  order, and performs no I/O. Return `None` when the check cannot judge a record
  (missing input, not visible to a credential) rather than passing it. With reuse
  it may receive only the records that changed.
- Set `compares_across_records = True` whenever another record can change this
  record's result. Leaving it False on such a check serves stale results.
- Keep the check's logic in its own module. The hash covers that file only, so a
  helper imported from elsewhere can change without invalidating reuse.

Registration fails at import time for a bad module name, a repeated key, or a
missing `description` or `source`; an unknown source fails the build.

## Adding a source

Subclass `Source` in `sources.py` with a unique `name`, a `record_kind`, and a
`system` (`docdb`, `s3`, ...), and implement `fetch(previous)` to return a
DataFrame with columns `record_id`, `name`, `location`, `record_last_modified`,
plus any names in `extra_fields`.

- `Source.load` validates for you: records without a string `record_id` and a
  non-empty string `name` are skipped and logged, a repeated `record_id` is kept
  once, and a source that returns no records fails the run.
- `previous` holds this source's rows from the current snapshot. Use it to skip
  refetching records whose last-modified timestamp has not changed (sweep IDs and
  timestamps, fetch only new or changed records). Records missing from the
  current fetch drop out of the snapshot.
- Page DocDB sweeps by `_id` (`{"_id": {"$gt": last_id}}`, sorted, with a limit)
  rather than by skip, so concurrent writes cannot drop or repeat records.
- Return null `record_last_modified` when the system has no per-record
  timestamp; those records are always re-evaluated.
- Declare I/O properties on the source, never on a check.
- Extra fields are not stored, so `previous` never contains them; a source with
  extra fields refetches them every run.
- Read credentials from the environment at fetch time and raise a clear error
  when they are missing. `code_ocean_data_assets` reads its Code Ocean API token
  from `CUSTOM_KEY`, which the sync capsule provides.

## Design decisions

- **Snapshot, not history.** The table mirrors live state; there is no
  `first_failed_at` or run log. Reuse needs only the previous snapshot.
- **Derived identity and versions.** The key comes from the module filename and
  the version from the module hash, so nothing is hand-maintained.
- **Per-record comparison, not a watermark.** A record is unchanged only when its
  stored and live last-modified timestamps are equal. A `last_modified > last run`
  watermark misses records written with older timestamps and cannot see deletions.
- **All or nothing.** Any source or check failure fails the job; nothing is
  written and the previous snapshot stays published. The results table is
  written before the checks table; a run that dies between the two leaves
  different `checked_at` values, which the page reports.
- **Per-check facts in their own table.** Description, source link, hash, counts,
  and timings have one value per check, so they live in `record_consistency_checks`
  rather than repeating on every result row, which the browser would otherwise
  materialize per row.
- **Sources own I/O.** Checks stay pure and testable; credentials, cost, and
  change signals are properties of a source.
- **Skip rather than pass.** A record a check cannot judge gets no result row,
  so pass counts only cover records that were actually compared. Coverage gaps
  (for example, v2 records without a Code Ocean ID) belong in their own check.

## Running and testing

- Nightly: `BIODATA_CACHE_SYNC_JOB=record_consistency_checks`, after
  `asset_basics`; it builds both tables and publishes both registry fragments.
  Locally: `record_consistency_results(force_update=True)`, or
  `force_full_rerun=True` to ignore the previous snapshot.
- Tests live in `tests/cache_table_helpers/record_consistency/` and stay offline.
  The `isolated` fixture in `conftest.py` swaps in empty registries and loads
  fake sources and checks from temporary modules, so framework tests do not
  depend on the real checks.
- The job logs, per source, records loaded and skipped, and per check, records
  evaluated, reused, and failed; the checks table records the same counts and
  timings.
