"""SmartSPIM assets cache table."""

import json
import logging

import boto3
import pandas as pd
from aind_data_access_api.document_db import MetadataDbClient

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.asset_basics import asset_basics
from biodata_cache.cache_table_helpers.source_data import source_data
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

NEUROGLANCER_BASE = "https://allen.neuroglass.io/new#!"
AIND_OPEN_DATA_BUCKET = "aind-open-data"


def _stitched_link(location: str) -> str:
    return f"{NEUROGLANCER_BASE}{location}/neuroglancer_config.json"


def _segmentation_link(location: str, channel: str) -> str:
    return f"{NEUROGLANCER_BASE}{location}/image_cell_segmentation/{channel}/visualization/neuroglancer_config.json"


def _quantification_link(location: str, channel: str) -> str:
    return f"{NEUROGLANCER_BASE}{location}/image_cell_quantification/{channel}/visualization/neuroglancer_config.json"


def _alignment_tissue_link(location: str) -> str:
    return f"{NEUROGLANCER_BASE}{location}/image_atlas_alignment/neuroglancer_config.json"


def _alignment_ccf_link(location: str) -> str:
    return f"{NEUROGLANCER_BASE}{location}/image_atlas_alignment/ccf_visualization/neuroglancer_config.json"


def _list_channels(location: str) -> list[str]:
    """List channel subfolders under image_cell_segmentation/ for a given asset location."""
    s3_client = boto3.client("s3")
    prefix = location.replace(f"s3://{AIND_OPEN_DATA_BUCKET}/", "") + "/image_cell_segmentation/"
    result = s3_client.list_objects_v2(
        Bucket=AIND_OPEN_DATA_BUCKET,
        Prefix=prefix,
        Delimiter="/",
    )
    return [cp["Prefix"].rstrip("/").split("/")[-1] for cp in result.get("CommonPrefixes", [])]


def _fetch_raw_ng_link(raw_name: str) -> str | None:
    """Fetch the ng_link from a raw asset's SPIM/derivatives/neuroglancer_config.json."""
    s3_client = boto3.client("s3")
    key = f"{raw_name}/SPIM/derivatives/neuroglancer_config.json"
    try:
        obj = s3_client.get_object(Bucket=AIND_OPEN_DATA_BUCKET, Key=key)
        config = json.loads(obj["Body"].read())
        link = config.get("ng_link")
        if link and "/derivatives/" in link and "/SPIM/derivatives/" not in link:
            link = link.replace("/derivatives/", "/SPIM/derivatives/")
        return link
    except Exception:
        return None


def _fetch_asset_metadata(asset_names: list[str]) -> dict[str, dict]:
    """Fetch location and processing metadata for stitched assets from the document DB."""
    client = MetadataDbClient(
        host=registry.API_GATEWAY_HOST,
        version="v2",
    )
    fields = [
        "name",
        "data_description.institution",
        "processing.data_processes",
        "location",
    ]
    projection = {field: 1 for field in fields + ["_id"]}
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
    raw_to_stitched: dict[str, str | None],
    metadata: dict[str, dict],
    raw_ng_links: dict[str, str | None] | None = None,
) -> list[dict]:
    """Build one row per (raw asset, channel) in long form.

    Processed assets with N channels produce N rows. Processed assets with no
    channels yet, and unprocessed assets, produce a single row with channel=None.
    """
    if raw_ng_links is None:
        raw_ng_links = {}
    rows = []
    for raw_name, stitched_name in raw_to_stitched.items():
        processed = stitched_name is not None
        raw_link = raw_ng_links.get(raw_name)

        if processed:
            record = metadata.get(stitched_name, {})
            location = record.get("location", "")
            institution_obj = record.get("data_description", {}).get("institution", {})
            institution = institution_obj.get("abbreviation", None) if institution_obj else None
            data_processes = record.get("processing", {}).get("data_processes", []) or []
            processing_end_time = data_processes[-1].get("end_date_time", None) if data_processes else None
            stitch_link = _stitched_link(location) if location else None
            channels = _list_channels(location) if location else []

            tissue_link = _alignment_tissue_link(location) if location else None
            ccf_link = _alignment_ccf_link(location) if location else None
            if channels:
                for channel in channels:
                    rows.append(
                        {
                            "name": stitched_name,
                            "raw_name": raw_name,
                            "processed": True,
                            "institution": institution,
                            "processing_end_time": processing_end_time,
                            "stitched_link": stitch_link,
                            "raw_link": raw_link,
                            "channel": channel,
                            "segmentation_link": _segmentation_link(location, channel),
                            "quantification_link": _quantification_link(location, channel),
                            "alignment_link": tissue_link,
                            "alignment_ccf_link": ccf_link,
                        }
                    )
            else:
                rows.append(
                    {
                        "name": stitched_name,
                        "raw_name": raw_name,
                        "processed": True,
                        "institution": institution,
                        "processing_end_time": processing_end_time,
                        "stitched_link": stitch_link,
                        "raw_link": raw_link,
                        "channel": None,
                        "segmentation_link": None,
                        "quantification_link": None,
                        "alignment_link": tissue_link,
                        "alignment_ccf_link": ccf_link,
                    }
                )
        else:
            rows.append(
                {
                    "name": raw_name,
                    "raw_name": raw_name,
                    "processed": False,
                    "institution": None,
                    "processing_end_time": None,
                    "stitched_link": None,
                    "raw_link": raw_link,
                    "channel": None,
                    "segmentation_link": None,
                    "quantification_link": None,
                    "alignment_link": None,
                    "alignment_ccf_link": None,
                }
            )
    return rows


@registry.register_table(registry.NAMES["smartspim"])
def assets_smartspim(force_update: bool = False) -> pd.DataFrame:
    """Build a long-form DataFrame of SmartSPIM assets with one row per (asset, channel).

    Fetches raw SPIM assets from asset_basics, finds the latest stitched derived
    asset for each via source_data, then enriches with S3 channel links from
    image_cell_segmentation/ and the raw neuroglancer link from the raw asset's
    SPIM/derivatives/neuroglancer_config.json. Results are cached.

    Args:
        force_update: If True, bypass cache and rebuild from database and S3.

    Returns:
        DataFrame with one row per (asset, channel) and columns:
        name, raw_name, processed, processing_end_time, stitched_link, raw_link,
        channel, segmentation_link, quantification_link.
    """
    df = registry.BACKEND.read(registry.NAMES["smartspim"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["smartspim"],
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
        raw_spim = raw_spim[~raw_spim["instrument_id"].str.contains("exa", case=False, na=False)]
        raw_spim_names = list(raw_spim["name"].dropna())

        sd = source_data()
        stitched_candidates = sd[
            sd["source_data"].isin(raw_spim_names) & sd["name"].str.contains("stitched", case=False, na=False)
        ].copy()
        stitched_candidates = (
            stitched_candidates.sort_values("processing_time", ascending=False)
            .groupby("source_data", as_index=False)
            .first()
        )
        raw_to_stitched_series = stitched_candidates.set_index("source_data")["name"]
        raw_to_stitched = {name: raw_to_stitched_series.get(name) for name in raw_spim_names}

        stitched_names = [v for v in raw_to_stitched.values() if v is not None]

        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["smartspim"],
                message=f"Fetching metadata for {len(stitched_names)} stitched and {len(raw_spim_names) - len(stitched_names)} unprocessed assets",
            ).to_json()
        )

        metadata = _fetch_asset_metadata(stitched_names)
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["smartspim"],
                message=f"Fetched metadata for {len(metadata)} assets, fetching raw neuroglancer links from S3",
            ).to_json()
        )
        raw_ng_links = {name: _fetch_raw_ng_link(name) for name in raw_spim_names}
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["smartspim"],
                message=f"Fetched {sum(v is not None for v in raw_ng_links.values())} raw neuroglancer links, building rows",
            ).to_json()
        )
        rows = _build_rows(raw_to_stitched, metadata, raw_ng_links)
        df = pd.DataFrame(rows)

        registry.BACKEND.write(registry.NAMES["smartspim"], df)

    return df


def assets_smartspim_columns() -> list[Column]:
    return [
        Column(name="name", description="Asset name (stitched if available, otherwise raw)"),
        Column(name="raw_name", description="Raw asset name"),
        Column(name="processed", description="Whether a stitched derived asset exists"),
        Column(name="institution", description="Institution abbreviation"),
        Column(name="processing_end_time", description="Processing end time for stitched asset"),
        Column(name="stitched_link", description="Neuroglancer link to stitched asset"),
        Column(
            name="raw_link", description="Neuroglancer link from raw asset's SPIM/derivatives/neuroglancer_config.json"
        ),
        Column(name="channel", description="Channel name (e.g. Ex_561_Em_600), or None if unprocessed"),
        Column(name="segmentation_link", description="Neuroglancer segmentation link for this channel"),
        Column(name="quantification_link", description="Neuroglancer quantification link for this channel"),
        Column(name="alignment_link", description="Neuroglancer link to image_atlas_alignment/neuroglancer_config.json"),
        Column(name="alignment_ccf_link", description="Neuroglancer link to image_atlas_alignment/ccf_visualization/neuroglancer_config.json"),
    ]
