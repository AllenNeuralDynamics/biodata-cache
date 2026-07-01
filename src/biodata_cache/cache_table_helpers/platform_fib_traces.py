"""Fiber photometry processed dF/F trace cache table (partitioned by asset_name).

Pulls the processed dF/F time series from the per-session NWB (Zarr) files on S3
and stores them in wide form, one partition per processed asset. Each dF/F method
is a column rather than a row: within a given channel and fiber, all methods share
identical timestamps (the same camera frames), so there is no benefit to the long
layout. Fibers that have no Probe implant listed in the asset's procedures are
dropped, as their traces are junk data.
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
_PRIMARY_METHOD = "dff-bright_mc-iso-IRLS"
_FALLBACK_METHOD = "dff-bright"
_S3_URI_RE = re.compile(r"^s3://([^/]+)/(.+)$")
_FIBER_NAME_RE = re.compile(r"fiber[\s_]*(\d+)", re.IGNORECASE)
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


def _fetch_implanted_fibers(asset_name: str) -> set[int]:
    """Return the set of fiber indices with a Probe implant in the asset's procedures.

    Walks subject_procedures -> surgery procedures -> Probe implant entries and
    parses the implanted fiber index from the device name (e.g. 'Fiber_0' -> 0).
    Fibers absent from this set produce junk traces and should be discarded.
    """
    from aind_data_access_api.document_db import MetadataDbClient

    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
    records = client.retrieve_docdb_records(
        filter_query={"name": asset_name},
        projection={"procedures.subject_procedures": 1, "_id": 1},
        limit=0,
    )
    fibers: set[int] = set()
    for record in records:
        procs_root = record.get("procedures") or {}
        for subject_proc in procs_root.get("subject_procedures") or []:
            for proc in subject_proc.get("procedures") or []:
                if proc.get("object_type") != "Probe implant":
                    continue
                device = proc.get("implanted_device") or {}
                match = _FIBER_NAME_RE.match(device.get("name") or "")
                if match:
                    fibers.add(int(match.group(1)))
    return fibers


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


def _extract_session_traces(root, implanted_fibers: set[int]) -> pd.DataFrame:
    """Build a wide-form DataFrame of dF/F traces for a single session's NWB root.

    One row per (channel, fiber, sample). Timestamps are shared across all dF/F
    methods for a given channel and fiber, so methods become columns rather than
    rows. Only fibers present in ``implanted_fibers`` are kept.
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
        if fiber_idx not in implanted_fibers:
            continue
        if method not in (_PRIMARY_METHOD, _FALLBACK_METHOD):
            continue
        series = fp[series_name]
        data = series["data"][:]
        timestamps = series["timestamps"][:]
        n = min(len(data), len(timestamps))
        key = (channel, fiber_idx)
        if key not in groups:
            groups[key] = {"timestamp": timestamps[:n]}
        groups[key][method] = data[:n].astype("float32")

    for key in groups:
        if _PRIMARY_METHOD in groups[key] and _FALLBACK_METHOD in groups[key]:
            del groups[key][_FALLBACK_METHOD]

    if not groups:
        return pd.DataFrame()

    frames = []
    for (channel, fiber_idx), cols in groups.items():
        frame = pd.DataFrame(cols)
        frame["fiber"] = fiber_idx
        frame["channel"] = channel
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    method_cols = sorted(c for c in df.columns if c not in {"timestamp", "fiber", "channel"})
    return df[["fiber", "channel", "timestamp"] + method_cols]


def _fetch_asset_fib_traces(asset_name: str, location: str | None = None) -> pd.DataFrame:
    """Fetch and cache the processed dF/F traces for one asset from its S3 NWB file.

    Only fibers with a Probe implant in the asset's procedures are kept; the rest
    are junk and are discarded. Returns an empty DataFrame; callers should read
    back from the backend.

    Args:
        asset_name: Processed asset name whose fiber traces to fetch.
        location: The asset's S3 location. When provided (bulk sync path), the
            full asset_basics table is not read; when None (single-asset path),
            the location is looked up from asset_basics.
    """
    setup_logging()
    cache_key = f"{registry.NAMES['fib_traces']}/{asset_name}"
    _log(f"Updating cache for asset {asset_name}")

    registry.BACKEND.clear_partition(cache_key)

    if location is None:
        basics = asset_basics()
        asset = basics[basics["name"] == asset_name]
        if asset.empty:
            _log(f"Asset {asset_name} not found in asset_basics")
            return pd.DataFrame()
        location = asset.iloc[0]["location"]

    if not location:
        _log(f"No location for asset {asset_name}")
        return pd.DataFrame()

    implanted_fibers = _fetch_implanted_fibers(asset_name)
    if not implanted_fibers:
        _log(f"No fiber implants found in procedures for asset {asset_name}")
        return pd.DataFrame()

    root = _open_nwb_zarr(location)
    if root is None:
        _log(f"No NWB file found for asset {asset_name}")
        return pd.DataFrame()

    session_df = _extract_session_traces(root, implanted_fibers)
    del root
    if session_df.empty:
        _log(f"No fiber traces extracted for asset {asset_name}")
        return pd.DataFrame()

    session_df = session_df.sort_values(["channel", "timestamp", "fiber"]).reset_index(drop=True)
    registry.BACKEND.write(cache_key, session_df)
    _log(f"Cached fib traces for asset {asset_name}")
    return pd.DataFrame()


@registry.register_table(registry.NAMES["fib_traces"])
def platform_fib_traces(
    asset_name: str,
    force_update: bool = False,
    lazy: bool = False,
    location: str | None = None,
) -> pd.DataFrame | str:
    """Return processed fiber photometry dF/F traces for a single asset.

    One row per sample of every processed dF/F series found in the session NWB
    file (channels G/R/Iso, each implanted fiber index, every dF/F method variant).
    Fibers without a Probe implant in the asset's procedures are excluded. Data is
    cached per asset_name partition.

    Args:
        asset_name: Processed asset name whose fiber traces to fetch.
        force_update: If True, bypass cache and pull fresh data from the S3 NWB
            file, writing the result to the cache. An empty DataFrame is returned;
            read again without force_update (or use lazy=True) to retrieve the data.
        lazy: If True, return the partition's storage location string (for DuckDB)
            instead of loading the DataFrame.
        location: Optional S3 location of the asset. When provided during a
            force_update, the full asset_basics table is not read (used by the
            bulk sync to avoid re-reading asset_basics once per asset).

    Returns:
        DataFrame with columns fiber, channel, timestamp, and one column per dF/F
        method; the partition location string if lazy=True; or an empty DataFrame
        if force_update=True (data is written to the cache).

    Raises:
        ValueError: If the cache is empty for the asset and force_update is False.
    """
    cache_key = f"{registry.NAMES['fib_traces']}/{asset_name}"

    if lazy:
        if force_update:
            _fetch_asset_fib_traces(asset_name, location=location)
        return registry.BACKEND.get_location(cache_key)

    if force_update:
        return _fetch_asset_fib_traces(asset_name, location=location)

    df = registry.BACKEND.read(cache_key)
    if df.empty:
        raise ValueError(
            f"Cache is empty for asset {asset_name}. Use force_update=True to fetch data from S3."
        )

    return df


def platform_fib_traces_columns() -> list[Column]:
    """Return platform_fib_traces cache table column definitions."""
    return [
        Column(name="fiber", description="Fiber index (0-3); joinable with platform_fib fiber 'Fiber <n>'"),
        Column(name="channel", description="Signal channel: G (green), R (red), or Iso (isosbestic)"),
        Column(name="timestamp", description="Sample timestamp in seconds (acquisition clock)"),
        Column(name="dff-bright", description="dF/F using brightest-pixel baseline"),
    ]
