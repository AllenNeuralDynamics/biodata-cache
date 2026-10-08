"""ExaSPIM intermediate-folder inventory for metadata-seeded acquisition chains."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlsplit

import boto3
import pandas as pd
import pyarrow as pa
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.asset_basics import asset_basics
from biodata_cache.models import Column
from biodata_cache.utils import setup_logging

FOLDERS = {
    "fused_present": "fusion/fused.zarr/",
    "fused_ccf_present": "fusion/fused_ccf_ch.zarr/",
    "flatfield_present": "flatfield_correction/SPIM.ome.zarr/",
    "denoised_present": "denoised/SPIM.ome.zarr/",
}
REQUIRED_KEYS = ("fused_present", "fused_ccf_present")
INTERMEDIATE_KEYS = ("flatfield_present", "denoised_present")
COLUMN_DESCRIPTIONS = {
    "raw_name": "Raw acquisition seeding this asset chain",
    "subject_id": "Subject ID from the raw acquisition",
    "project_name": "Project from the raw acquisition",
    "name": "Inspected derived asset name, null when no candidate was found",
    "location": "Inspected asset's S3 root",
    "discovery_source": "docdb or s3, null when discovery did not find a candidate",
    "docdb_id": "Derived asset's DocDB ID when discovered through metadata",
    "checked_at": "UTC timestamp of the folder inspection or discovery outcome",
    "fused_present": "Whether fusion/fused.zarr/ contains an object",
    "fused_ccf_present": "Whether fusion/fused_ccf_ch.zarr/ contains an object",
    "flatfield_present": "Whether flatfield_correction/SPIM.ome.zarr/ contains an object",
    "denoised_present": "Whether denoised/SPIM.ome.zarr/ contains an object",
    "has_intermediates": "Whether either intermediate folder exists; null when unknown",
    "eligible_for_cleanup": "Both fusion folders and at least one intermediate exist; not a completeness check",
    "status": "ok, missing_required, no_intermediates, no_processed, invalid_location, or s3_error",
    "error_code": "S3 error code or exception type, without request URLs or credentials",
    "missing_required_folders": "Required fusion paths confirmed absent",
    "intermediate_uris": "S3 URIs of intermediate folders confirmed present, regardless of fusion prerequisites",
    "output_uris": "Intermediate S3 URIs meeting the original script's fusion prerequisites",
}
BOOLEAN_COLUMNS = (*FOLDERS, "has_intermediates", "eligible_for_cleanup")
LIST_COLUMNS = ("missing_required_folders", "intermediate_uris", "output_uris")


def _s3_root(location: str) -> tuple[str, str]:
    """Parse an S3 asset location without inventing a bucket or prefix."""
    if not isinstance(location, str):
        raise ValueError("Missing S3 location")
    uri = urlsplit(location)
    prefix = uri.path.lstrip("/").rstrip("/")
    if uri.scheme != "s3" or not uri.netloc or not prefix or uri.query or uri.fragment:
        raise ValueError("Invalid S3 location")
    return uri.netloc, prefix + "/"


def _source_index(source_rows: pd.DataFrame) -> dict[str, set[str]]:
    """Index cached provenance once for local descendant traversal."""
    edges = {}
    if {"name", "source_data"}.issubset(source_rows.columns):
        for name, source in source_rows[["name", "source_data"]].itertuples(index=False, name=None):
            if isinstance(name, str) and isinstance(source, str) and source:
                edges.setdefault(source, set()).add(name)
    return edges


def _descendants(raw_name: str, edges: dict[str, set[str]]) -> set[str]:
    """Find transitive descendants locally, including renamed stages and cycles."""
    seen = {raw_name}
    frontier = [raw_name]
    while frontier:
        name = frontier.pop()
        for child in edges.get(name, ()):
            if child not in seen:
                seen.add(child)
                frontier.append(child)
    return seen - {raw_name}


def _candidate_names(snapshot: dict, edges: dict, raw_name: str) -> set[str]:
    """Include provenance descendants of acquisition-prefixed stages with missing source metadata."""
    names = _descendants(raw_name, edges)
    for name in snapshot:
        if name.startswith(raw_name + "_"):
            names.add(name)
            names.update(_descendants(name, edges))
    return names


def _docdb_snapshot(client, raw_names: list[str], source_rows: pd.DataFrame) -> tuple[dict, dict]:
    """Load ExaSPIM metadata once, plus batched name lookups for renamed descendants."""
    edges = _source_index(source_rows)
    projection = {"name": 1, "location": 1, "_id": 1, "data_description.source_data": 1}
    logging.info("Loading registered ExaSPIM derived metadata")
    records = client.retrieve_docdb_records(
        filter_query={"data_description.data_level": "derived", "name": {"$regex": "^exaSPIM_"}},
        projection=projection,
        limit=0,
    )
    snapshot = {}

    def index(records):
        for record in records:
            name = record.get("name")
            if not isinstance(name, str):
                continue
            snapshot[name] = dict(record, discovery_source="docdb")
            sources = (record.get("data_description") or {}).get("source_data") or []
            if isinstance(sources, str):
                sources = [sources]
            for source in sources:
                if isinstance(source, str) and source:
                    edges.setdefault(source, set()).add(name)

    index(records)
    wanted = set().union(*(_candidate_names(snapshot, edges, name) for name in raw_names))
    missing = sorted(wanted - snapshot.keys())
    for start in range(0, len(missing), 20):
        index(
            client.retrieve_docdb_records(
                filter_query={"data_description.data_level": "derived", "name": {"$in": missing[start : start + 20]}},
                projection=projection,
                limit=0,
            )
        )
    logging.info("Loaded %s registered derived assets; resolved provenance locally", len(snapshot))
    return snapshot, edges


def _docdb_candidates(snapshot: dict, edges: dict, raw_name: str) -> list[dict]:
    """Select a raw chain from the shared snapshot without additional database calls."""
    names = _candidate_names(snapshot, edges, raw_name)
    return [snapshot[name] for name in sorted(names) if name in snapshot and name != raw_name]


def _s3_candidates(s3, raw: dict) -> list[dict]:
    """Discover combined processed folders beside the raw acquisition's S3 location."""
    bucket, root = _s3_root(raw.get("location"))
    parent = root.rstrip("/").rpartition("/")[0]
    prefix = (parent + "/" if parent else "") + raw["name"] + "_processed_"
    candidates = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for item in page.get("CommonPrefixes", []):
            key = item["Prefix"]
            candidates[key] = {
                "name": key.rstrip("/").rsplit("/", 1)[-1],
                "location": f"s3://{bucket}/{key.rstrip('/')}",
                "discovery_source": "s3",
            }
    return [candidates[key] for key in sorted(candidates)]


def _error_code(exc: Exception) -> str:
    """Return a compact error code suitable for the public cache."""
    if isinstance(exc, ClientError):
        return str(exc.response.get("Error", {}).get("Code", "ClientError"))
    return type(exc).__name__


def _empty_row(raw: dict) -> dict:
    """Create an unknown inspection result for a raw acquisition."""
    return {
        **dict.fromkeys(COLUMN_DESCRIPTIONS),
        "raw_name": raw["name"],
        "subject_id": raw.get("subject_id"),
        "project_name": raw.get("project_name"),
        "checked_at": datetime.now(timezone.utc),
        **{key: [] for key in LIST_COLUMNS},
    }


def _inspect(s3, raw: dict, candidate: dict) -> dict:
    """Check all four prefixes and apply the original script's eligibility criteria."""
    row = _empty_row(raw)
    row.update({key: candidate.get(key) for key in ("name", "location", "discovery_source")})
    row["docdb_id"] = candidate.get("_id")
    try:
        bucket, root = _s3_root(row["location"])
    except ValueError:
        row["status"] = "invalid_location"
        return row

    errors = []
    for key, folder in FOLDERS.items():
        try:
            response = s3.list_objects_v2(Bucket=bucket, Prefix=root + folder, MaxKeys=1)
            row[key] = response.get("KeyCount", 0) > 0
        except (BotoCoreError, ClientError) as exc:
            errors.append(_error_code(exc))
    row["missing_required_folders"] = [FOLDERS[key] for key in REQUIRED_KEYS if row[key] is False]
    row["intermediate_uris"] = [f"s3://{bucket}/{root}{FOLDERS[key]}" for key in INTERMEDIATE_KEYS if row[key] is True]
    if row["intermediate_uris"]:
        row["has_intermediates"] = True
    elif all(row[key] is False for key in INTERMEDIATE_KEYS):
        row["has_intermediates"] = False
    if errors:
        row.update(status="s3_error", error_code=", ".join(sorted(set(errors))))
    else:
        required = all(row[key] for key in REQUIRED_KEYS)
        row["eligible_for_cleanup"] = required and row["has_intermediates"]
        row["output_uris"] = row["intermediate_uris"] if row["eligible_for_cleanup"] else []
        row["status"] = "missing_required" if not required else "ok" if row["has_intermediates"] else "no_intermediates"
    return row


def _frame(rows: list[dict]) -> pd.DataFrame:
    """Keep Parquet types stable for empty inventories and unknown results."""
    df = pd.DataFrame(rows, columns=list(COLUMN_DESCRIPTIONS))
    for key in COLUMN_DESCRIPTIONS:
        if key in BOOLEAN_COLUMNS:
            df[key] = df[key].astype("boolean")
        elif key in LIST_COLUMNS:
            df[key] = df[key].astype(pd.ArrowDtype(pa.list_(pa.string())))
        elif key == "checked_at":
            df[key] = pd.to_datetime(df[key], utc=True)
        else:
            df[key] = df[key].astype("string")
    return df


@registry.register_table(registry.NAMES["exaspim_intermediates"])
def platform_exaspim_intermediates(force_update: bool = False, *, workers: int = 8) -> pd.DataFrame:
    """Read the inventory or rebuild every metadata-seeded raw exaSPIM chain."""
    if workers < 1:
        raise ValueError("workers must be at least 1")
    table = registry.NAMES["exaspim_intermediates"]
    if not force_update:
        if not registry.BACKEND.cache_exists(table):
            raise ValueError("Cache is empty. Use force_update=True to build the inventory.")
        return registry.BACKEND.read(table)

    setup_logging()
    basics = asset_basics(
        modality="SPIM",
        data_level="raw",
        limit=None,
        columns=["name", "location", "instrument_id", "subject_id", "project_name"],
    )
    raw_assets = basics[basics["instrument_id"].str.contains("exa", case=False, na=False)]
    raw_assets = raw_assets.dropna(subset=["name"]).drop_duplicates("name").sort_values("name")
    rows = []
    logging.info("ExaSPIM intermediates: assessing %s raw chains", len(raw_assets))
    if not raw_assets.empty:
        from aind_data_access_api.document_db import MetadataDbClient

        client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
        s3 = boto3.client(
            "s3", config=Config(max_pool_connections=workers * 2, retries={"mode": "adaptive", "max_attempts": 5})
        )
        source_rows = registry.BACKEND.read(registry.NAMES["d2r"])
        raw_records = raw_assets.to_dict("records")
        snapshot, edges = _docdb_snapshot(client, [raw["name"] for raw in raw_records], source_rows)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = []
            for index, raw in enumerate(raw_records, start=1):
                logging.info("ExaSPIM chain %s/%s: %s", index, len(raw_assets), raw["name"])
                candidates = _docdb_candidates(snapshot, edges, raw["name"])
                logging.info("ExaSPIM chain %s/%s: %s registered descendants", index, len(raw_assets), len(candidates))
                futures.append(pool.submit(_assess_candidates, s3, raw, candidates))
            for index, future in enumerate(as_completed(futures), start=1):
                rows.extend(future.result())
                logging.info("ExaSPIM S3 checks: %s/%s chains finished", index, len(futures))
    df = _frame(rows).sort_values(["raw_name", "name"], na_position="last").reset_index(drop=True)
    registry.BACKEND.write(table, df)
    logging.info(
        "ExaSPIM intermediates: %s raw chains, %s rows; statuses %s",
        len(raw_assets),
        len(df),
        df.status.value_counts().to_dict(),
    )
    return df


def _assess_candidates(s3, raw: dict, candidates: list[dict]) -> list[dict]:
    """Assess resolved candidates with an S3 fallback for unregistered chains."""
    if not candidates:
        try:
            candidates = _s3_candidates(s3, raw)
        except (ValueError, BotoCoreError, ClientError) as exc:
            row = _empty_row(raw)
            row.update(
                status="invalid_location" if isinstance(exc, ValueError) else "s3_error", error_code=_error_code(exc)
            )
            return [row]
    if not candidates:
        row = _empty_row(raw)
        row["status"] = "no_processed"
        return [row]
    return [_inspect(s3, raw, candidate) for candidate in candidates]


def platform_exaspim_intermediates_columns() -> list[Column]:
    """Return the published intermediate-inventory column contract."""
    return [Column(name=name, description=description) for name, description in COLUMN_DESCRIPTIONS.items()]
