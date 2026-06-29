"""Fiber photometry processed dF/F trace cache table (partitioned by subject_id).

Pulls the processed dF/F time series from the per-session NWB (Zarr) files on S3
and stores them in wide form, partitioned by subject_id. Each dF/F method is a
column rather than a row: within a given channel and fiber, all methods share
identical timestamps (the same camera frames), so there is no benefit to the long
layout. Implants are stable per subject over time, making subject_id a safe
partition key.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor

import boto3
import pandas as pd
from botocore.config import Config

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.asset_basics import asset_basics
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

_FP_GROUP = "processing/fiber_photometry"
_SERIES_RE = re.compile(r"^(G|R|Iso)_(\d+)_(.+)$")
_S3_URI_RE = re.compile(r"^s3://([^/]+)/(.+)$")
_MAX_WORKERS = 32


def _log(message: str) -> None:
    """Emit a structured cache log message for the fib_traces table."""
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["fib_traces"],
            message=message,
        ).to_json()
    )


def _parse_s3(location: str) -> tuple[str, str]:
    """Split an ``s3://bucket/key`` URI into ``(bucket, key)`` with no trailing slash."""
    match = _S3_URI_RE.match(location)
    if match is None:
        raise ValueError(f"Not an S3 URI: {location}")
    return match.group(1), match.group(2).rstrip("/")


def _find_nwb_prefix(client, bucket: str, key: str) -> str | None:
    """Return the S3 key prefix of the ``*.nwb`` directory under ``<key>/nwb/``, or None."""
    resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{key}/nwb/", Delimiter="/")
    for entry in resp.get("CommonPrefixes", []):
        prefix = entry["Prefix"].rstrip("/")
        if prefix.endswith(".nwb"):
            return prefix
    return None


def _download_zarr_store(client, bucket: str, nwb_prefix: str) -> dict:
    """Concurrently download the consolidated metadata and fiber-photometry chunks.

    Only the consolidated ``.zmetadata`` and every object under the
    ``processing/fiber_photometry`` group are fetched (the dF/F data is tiny);
    nothing else in the NWB is downloaded. Returns an in-memory zarr store dict
    keyed by paths relative to the NWB root.
    """
    keys = [f"{nwb_prefix}/.zmetadata"]
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{nwb_prefix}/{_FP_GROUP}/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])

    def _fetch(s3_key: str) -> tuple[str, bytes]:
        """Download one object and return its NWB-relative key with bytes."""
        body = client.get_object(Bucket=bucket, Key=s3_key)["Body"].read()
        return s3_key[len(nwb_prefix) + 1 :], body

    store = {}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        for rel_key, body in executor.map(_fetch, keys):
            store[rel_key] = body
    return store


def _open_nwb_zarr(location: str):
    """Open the NWB Zarr group for an asset given its S3 location.

    Reads only the consolidated metadata and the processed dF/F chunks via boto3
    (concurrently), avoiding any full-file download. Returns the consolidated zarr
    root group, or None if no NWB file is found.
    """
    import zarr

    bucket, key = _parse_s3(location)
    client = boto3.client("s3", config=Config(max_pool_connections=_MAX_WORKERS))
    nwb_prefix = _find_nwb_prefix(client, bucket, key)
    if nwb_prefix is None:
        return None
    store = _download_zarr_store(client, bucket, nwb_prefix)
    return zarr.open_consolidated(store, mode="r")


def _extract_session_traces(root, asset_name: str, subject_id: str) -> pd.DataFrame:
    """Build a wide-form DataFrame of dF/F traces for a single session's NWB root.

    One row per (channel, fiber, sample). Timestamps are shared across all dF/F
    methods for a given channel and fiber, so methods become columns rather than rows.
    """
    if _FP_GROUP not in root:
        return pd.DataFrame()

    fp = root[_FP_GROUP]
    groups = {}
    for series_name in fp.group_keys():
        match = _SERIES_RE.match(series_name)
        if match is None:
            continue
        channel, fiber_idx, method = match.group(1), int(match.group(2)), match.group(3)
        if method != "dff-bright":
            continue
        series = fp[series_name]
        data = series["data"][:]
        timestamps = series["timestamps"][:]
        n = min(len(data), len(timestamps))
        key = (channel, fiber_idx)
        if key not in groups:
            groups[key] = {"timestamp": timestamps[:n]}
        groups[key][method] = data[:n].astype("float32")

    if not groups:
        return pd.DataFrame()

    frames = []
    for (channel, fiber_idx), cols in groups.items():
        frame = pd.DataFrame(cols)
        frame["fiber"] = fiber_idx
        frame["channel"] = channel
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    df["asset_name"] = asset_name
    df["subject_id"] = subject_id
    method_cols = sorted(c for c in df.columns if c not in {"timestamp", "fiber", "channel", "asset_name", "subject_id"})
    return df[["subject_id", "asset_name", "fiber", "channel", "timestamp"] + method_cols]


def _fetch_subject_fib_traces(subject_id: str) -> pd.DataFrame:
    """Fetch and cache all processed dF/F traces for a subject from S3 NWB files."""
    setup_logging()
    cache_key = f"{registry.NAMES['fib_traces']}/{subject_id}"
    _log(f"Updating cache for subject {subject_id}")

    basics = asset_basics()
    subject_assets = basics[basics["subject_id"] == subject_id]
    subject_assets = subject_assets[
        subject_assets["modalities"].apply(
            lambda x: x is not None and not isinstance(x, float) and any("fib" in m.lower() for m in x)
        )
    ]
    subject_assets = subject_assets[subject_assets["data_level"] == "derived"]

    frames = []
    for _, row in subject_assets.iterrows():
        location = row["location"]
        if not location:
            continue
        root = _open_nwb_zarr(location)
        if root is None:
            _log(f"No NWB file found for asset {row['name']}")
            continue
        session_df = _extract_session_traces(root, row["name"], subject_id)
        if not session_df.empty:
            frames.append(session_df)

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    _log(f"Cached fib traces for subject {subject_id} ({len(frames)} sessions, {len(df)} samples)")
    registry.BACKEND.write(cache_key, df)
    return df


@registry.register_table(registry.NAMES["fib_traces"])
def platform_fib_traces(
    subject_id: str,
    force_update: bool = False,
    lazy: bool = False,
) -> pd.DataFrame | str:
    """Return processed fiber photometry dF/F traces for a single subject.

    One row per sample of every processed dF/F series found in the session NWB
    files (channels G/R/Iso, each fiber index, every dF/F method variant). Data is
    cached per subject_id partition.

    Args:
        subject_id: Subject ID whose fiber traces to fetch.
        force_update: If True, bypass cache and pull fresh data from the S3 NWB files.
        lazy: If True, return the partition's storage location string (for DuckDB)
            instead of loading the DataFrame.

    Returns:
        DataFrame with columns subject_id, asset_name, fiber, channel, timestamp,
        and one column per dF/F method; or the partition location string if lazy=True.

    Raises:
        ValueError: If the cache is empty for the subject and force_update is False.
    """
    cache_key = f"{registry.NAMES['fib_traces']}/{subject_id}"

    if lazy:
        if force_update:
            _fetch_subject_fib_traces(subject_id)
        return registry.BACKEND.get_location(cache_key)

    df = registry.BACKEND.read(cache_key)

    if df.empty and not force_update:
        raise ValueError(
            f"Cache is empty for subject {subject_id}. Use force_update=True to fetch data from S3."
        )

    if force_update:
        df = _fetch_subject_fib_traces(subject_id)

    return df


def platform_fib_traces_columns() -> list[Column]:
    """Return platform_fib_traces cache table column definitions."""
    return [
        Column(name="subject_id", description="Subject ID (partition key)"),
        Column(name="asset_name", description="Processed asset name identifying the session"),
        Column(name="fiber", description="Fiber index (0-3); joinable with platform_fib fiber 'Fiber <n>'"),
        Column(name="channel", description="Signal channel: G (green), R (red), or Iso (isosbestic)"),
        Column(name="timestamp", description="Sample timestamp in seconds (acquisition clock)"),
        Column(name="dff-bright", description="dF/F using brightest-pixel baseline"),
    ]
