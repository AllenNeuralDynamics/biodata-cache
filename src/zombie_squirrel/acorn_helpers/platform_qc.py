"""Platform QC acorn: per-platform tag-level quality control status tables."""

import logging

import pandas as pd
from aind_data_access_api.document_db import MetadataDbClient

import zombie_squirrel.acorns as acorns
from zombie_squirrel.utils import SquirrelMessage, setup_logging

PLATFORM_FILTERS = {
    "spim": {
        "qc_modalities": {"SPIM"},
    },
    "fib": {
        "qc_modalities": {"fib"},
    },
    "vr": {
        "acquisition_type": "AindVrForaging",
        "qc_modalities": {"behavior", "behavior-videos"},
    },
    "dynamic_foraging": {
        "acquisition_type_regex": r"(Uncoupled|Coupled)( Without)? Baiting",
        "qc_modalities": {"behavior", "behavior-videos"},
    },
}

PLATFORMS = list(PLATFORM_FILTERS.keys())


def _filter_basics_pandas(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    """Filter asset_basics DataFrame to rows matching the given platform."""
    cfg = PLATFORM_FILTERS[platform]
    modality_pattern = "|".join(cfg["qc_modalities"])
    mask = df["modalities"].str.contains(modality_pattern, case=False, na=False)
    if "acquisition_type" in cfg:
        mask = mask & (df["acquisition_type"] == cfg["acquisition_type"])
    if "acquisition_type_regex" in cfg:
        mask = mask & df["acquisition_type"].str.match(cfg["acquisition_type_regex"], na=False)
    return df[mask]


def _filter_tags_by_modality(quality_control: dict, target_modalities: set[str]) -> list[tuple[str, str]]:
    """Return (tag_key, status) pairs from the status dict filtered by modality.

    A tag is included if:
    - At least one metric with that tag has a modality matching target_modalities, OR
    - The tag key itself is one of the target modalities (modality-level aggregation).
    """
    metrics = quality_control.get("metrics", [])
    status_dict = quality_control.get("status", {})
    if not isinstance(status_dict, dict) or not status_dict:
        return []

    tag_key_modalities: dict[str, set[str]] = {}
    for metric in metrics:
        modality = metric.get("modality")
        if isinstance(modality, dict):
            mod_abbr = modality.get("abbreviation", "")
        else:
            mod_abbr = ""

        tags = metric.get("tags") or {}
        if isinstance(tags, dict):
            for tag_type, tag_value in tags.items():
                key = f"{tag_type}:{tag_value}"
                tag_key_modalities.setdefault(key, set()).add(mod_abbr)

        if mod_abbr:
            tag_key_modalities.setdefault(mod_abbr, set()).add(mod_abbr)

    result = []
    for status_key, status_value in status_dict.items():
        associated_mods = tag_key_modalities.get(status_key, set())
        if associated_mods & target_modalities:
            result.append((status_key, status_value))
        elif status_key in target_modalities:
            result.append((status_key, status_value))

    return result


@acorns.register_acorn("platform_qc")
def platform_qc(platform: str, force_update: bool = False) -> pd.DataFrame:
    """Build a platform-level QC table with tag-level status data.

    Pulls quality_control metadata directly from DocDB, then filters tags
    to only those whose underlying metrics match the platform's modality.
    Joined with asset_basics for instrument and experimenter context.
    Results are cached per platform.

    Args:
        platform: One of 'spim', 'fib', 'vr', 'dynamic_foraging'.
        force_update: If True, bypass cache and rebuild from source data.

    Returns:
        DataFrame with columns: asset_name, subject_id, instrument_id, experimenter,
        tag, status, timestamp.
    """
    cache_key = f"platform_qc/{platform}"
    df = acorns.TREE.scurry(cache_key)

    if df.empty and not force_update:
        raise ValueError(f"Cache is empty for platform '{platform}'. Use force_update=True to rebuild.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn="platform_qc",
                message=f"Building platform QC for '{platform}'",
            ).to_json()
        )
        df = _build(platform)
        if not df.empty:
            acorns.TREE.hide(cache_key, df)

    return df


def _build(platform: str) -> pd.DataFrame:
    """Build platform QC by querying DocDB for quality_control in batches."""
    from zombie_squirrel.acorn_helpers.asset_basics import asset_basics

    basics_df = asset_basics()
    platform_df = _filter_basics_pandas(basics_df, platform)
    if platform_df.empty:
        return pd.DataFrame()

    cfg = PLATFORM_FILTERS[platform]
    target_modalities = cfg["qc_modalities"]

    asset_names = platform_df["name"].tolist()

    client = MetadataDbClient(
        host=acorns.API_GATEWAY_HOST,
        version="v2",
    )

    all_rows: list[dict] = []
    batch_size = 50
    for i in range(0, len(asset_names), batch_size):
        batch = asset_names[i : i + batch_size]
        records = client.retrieve_docdb_records(
            filter_query={"name": {"$in": batch}},
            projection={
                "name": 1,
                "quality_control": 1,
                "subject.subject_id": 1,
            },
            limit=0,
        )
        for record in records:
            qc_data = record.get("quality_control")
            if not qc_data:
                continue
            asset_name = record.get("name", "")
            subject_id = record.get("subject", {}).get("subject_id", "")
            filtered_tags = _filter_tags_by_modality(qc_data, target_modalities)
            for tag, tag_status in filtered_tags:
                all_rows.append({
                    "asset_name": asset_name,
                    "subject_id": subject_id,
                    "tag": tag,
                    "status": tag_status,
                })

    if not all_rows:
        return pd.DataFrame()

    qc_df = pd.DataFrame.from_records(all_rows)

    basics_sub = platform_df[["name", "subject_id", "instrument_id", "instrument_id_normalized", "experimenters", "acquisition_start_time"]].rename(
        columns={"name": "asset_name", "acquisition_start_time": "timestamp"}
    ).copy()

    merged = qc_df.merge(basics_sub, on=["asset_name", "subject_id"], how="inner")
    merged["instrument_id"] = merged["instrument_id"].fillna("(unknown)")
    merged["instrument_id_normalized"] = merged["instrument_id_normalized"].fillna("")
    merged["experimenters"] = merged["experimenters"].fillna("(unknown)").replace("", "(unknown)")

    rows: list[dict] = []
    for _, row in merged.iterrows():
        for exp in str(row["experimenters"]).split(","):
            r = row.to_dict()
            r["experimenter"] = exp.strip()
            rows.append(r)

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    result = result.drop(columns=["experimenters"])
    cols = ["asset_name", "subject_id", "instrument_id", "instrument_id_normalized", "experimenter", "tag", "status", "timestamp"]
    return result[[c for c in cols if c in result.columns]]
