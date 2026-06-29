"""ExaSPIM assets cache table."""

import logging

import boto3
import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.asset_basics import asset_basics
from biodata_cache.cache_table_helpers.source_data import source_data
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

NEUROGLANCER_DEMO_BASE = "https://neuroglancer-demo.appspot.com/#!"
AIND_OPEN_DATA_BUCKET = "aind-open-data"


def _fused_link(location: str) -> str:
    return f"{NEUROGLANCER_DEMO_BASE}{location}"


def _fetch_raw_ng_link(raw_name: str) -> str | None:
    """Return a neuroglancer link for a raw ExaSPIM asset using neuroglancer.json or process_output.json."""
    s3_client = boto3.client("s3")
    for filename in ("neuroglancer.json", "process_output.json"):
        key = f"{raw_name}/{filename}"
        try:
            s3_client.head_object(Bucket=AIND_OPEN_DATA_BUCKET, Key=key)
            return f"{NEUROGLANCER_DEMO_BASE}s3://{AIND_OPEN_DATA_BUCKET}/{raw_name}/{filename}"
        except Exception:
            continue
    return None


def _fetch_asset_metadata(asset_names: list[str]) -> dict[str, dict]:
    """Fetch location metadata for fused assets from the document DB."""
    from aind_data_access_api.document_db import MetadataDbClient
    client = MetadataDbClient(
        host=registry.API_GATEWAY_HOST,
        version="v2",
    )
    projection = {"name": 1, "location": 1, "_id": 1}
    BATCH_SIZE = 100
    all_records = []
    for i in range(0, len(asset_names), BATCH_SIZE):
        batch = asset_names[i : i + BATCH_SIZE]
        batch_records = client.retrieve_docdb_records(
            filter_query={"name": {"$in": batch}},
            projection=projection,
            limit=0,
        )
        all_records.extend(batch_records)
    return {record["name"]: record for record in all_records}


def _build_rows(
    raw_to_fused: dict[str, str | None],
    metadata: dict[str, dict],
    raw_ng_links: dict[str, str | None],
) -> list[dict]:
    rows = []
    for raw_name, fused_name in raw_to_fused.items():
        raw_link = raw_ng_links.get(raw_name)
        if fused_name is not None:
            record = metadata.get(fused_name, {})
            location = record.get("location", "")
            rows.append(
                {
                    "name": fused_name,
                    "raw_name": raw_name,
                    "processed": True,
                    "raw_link": raw_link,
                    "fused_link": _fused_link(location) if location else None,
                }
            )
        else:
            rows.append(
                {
                    "name": raw_name,
                    "raw_name": raw_name,
                    "processed": False,
                    "raw_link": raw_link,
                    "fused_link": None,
                }
            )
    return rows


@registry.register_table(registry.NAMES["exaspim"])
def platform_exaspim(force_update: bool = False) -> pd.DataFrame:
    df = registry.BACKEND.read(registry.NAMES["exaspim"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["exaspim"],
                message="Updating cache",
            ).to_json()
        )

        basics = asset_basics()
        raw_spim = basics[
            (basics["data_level"] == "raw")
            & basics["modalities"].apply(
                lambda x: x is not None and not isinstance(x, float) and any("SPIM" in m for m in x)
            )
        ]
        raw_spim = raw_spim[raw_spim["instrument_id"].str.contains("exa", case=False, na=False)]
        raw_spim_names = list(raw_spim["name"].dropna())

        sd = source_data()
        fused_candidates = sd[
            sd["source_data"].isin(raw_spim_names) & sd["name"].str.contains("fused", case=False, na=False)
        ].copy()
        fused_candidates = (
            fused_candidates.sort_values("processing_time", ascending=False)
            .groupby("source_data", as_index=False)
            .first()
        )
        raw_to_fused_series = fused_candidates.set_index("source_data")["name"]
        raw_to_fused = {name: raw_to_fused_series.get(name) for name in raw_spim_names}

        fused_names = [v for v in raw_to_fused.values() if v is not None]

        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["exaspim"],
                message=f"Fetching metadata for {len(fused_names)} fused and {len(raw_spim_names) - len(fused_names)} unprocessed assets",
            ).to_json()
        )

        metadata = _fetch_asset_metadata(fused_names)
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["exaspim"],
                message=f"Fetched metadata for {len(metadata)} assets, fetching raw neuroglancer links from S3",
            ).to_json()
        )
        raw_ng_links = {name: _fetch_raw_ng_link(name) for name in raw_spim_names}
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["exaspim"],
                message=f"Fetched {sum(v is not None for v in raw_ng_links.values())} raw neuroglancer links, building rows",
            ).to_json()
        )
        rows = _build_rows(raw_to_fused, metadata, raw_ng_links)
        df = pd.DataFrame(rows)

        registry.BACKEND.write(registry.NAMES["exaspim"], df)

    return df


def platform_exaspim_columns() -> list[Column]:
    return [
        Column(name="name", description="Asset name (fused if available, otherwise raw)"),
        Column(name="raw_name", description="Raw asset name"),
        Column(name="processed", description="Whether a fused derived asset exists"),
        Column(
            name="raw_link", description="Neuroglancer link from raw asset's neuroglancer.json or process_output.json"
        ),
        Column(name="fused_link", description="Neuroglancer link to fused asset"),
    ]
