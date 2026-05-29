"""Platform QC acorn: per-platform tag-level quality control status tables."""

import logging

import pandas as pd

import zombie_squirrel.acorns as acorns
from zombie_squirrel.utils import SquirrelMessage, setup_logging

PLATFORM_FILTERS_SQL = {
    "spim": "modalities ILIKE '%SPIM%'",
    "fib": "modalities ILIKE '%fib%'",
    "vr": "acquisition_type = 'AindVrForaging'",
    "dynamic_foraging": "acquisition_type SIMILAR TO '(Uncoupled|Coupled)( Without)? Baiting'",
}

PLATFORMS = list(PLATFORM_FILTERS_SQL.keys())


def _filter_basics_pandas(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    """Filter asset_basics DataFrame to rows matching the given platform."""
    if platform == "spim":
        return df[df["modalities"].str.contains("SPIM", case=False, na=False)]
    if platform == "fib":
        return df[df["modalities"].str.contains("fib", case=False, na=False)]
    if platform == "vr":
        return df[df["acquisition_type"] == "AindVrForaging"]
    if platform == "dynamic_foraging":
        return df[df["acquisition_type"].str.match(r"(Uncoupled|Coupled)( Without)? Baiting", na=False)]
    return pd.DataFrame()


@acorns.register_acorn("platform_qc")
def platform_qc(platform: str, force_update: bool = False) -> pd.DataFrame:
    """Build a platform-level QC table with tag-level status data.

    One row per (asset, tag) showing the aggregated pass/fail/pending status
    for that tag group. Joined with asset_basics for instrument and experimenter context.
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
    """Dispatch to the appropriate build implementation based on the active tree."""
    from zombie_squirrel.forest import S3Tree

    if isinstance(acorns.TREE, S3Tree):
        return _build_s3(platform)
    return _build_memory(platform)


def _build_s3(platform: str) -> pd.DataFrame:
    """Build platform QC using DuckDB for efficient S3 batch reads."""
    import boto3
    import duckdb

    bucket = acorns.TREE.bucket
    qc_prefix = "data-asset-cache/zs_qc/"
    tag_status_prefix = "data-asset-cache/zs_qc_tag_status/"

    s3_client = boto3.client("s3")
    paginator = s3_client.get_paginator("list_objects_v2")
    available_subjects: set[str] = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=tag_status_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".pqt"):
                available_subjects.add(key.split("/")[-1].replace(".pqt", ""))

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region = 'us-west-2';")

    asset_basics_url = f"s3://{bucket}/data-asset-cache/zs_asset_basics.pqt"
    con.execute(f"CREATE TABLE asset_basics AS SELECT * FROM read_parquet('{asset_basics_url}')")

    platform_subjects = set(
        con.execute(
            f"SELECT DISTINCT subject_id FROM asset_basics WHERE {PLATFORM_FILTERS_SQL[platform]}"
        ).fetchdf()["subject_id"].dropna().tolist()
    )

    matching = platform_subjects & available_subjects
    if not matching:
        con.close()
        return pd.DataFrame()

    qc_urls = [f"s3://{bucket}/{tag_status_prefix}{sid}.pqt" for sid in sorted(matching)]
    qc_url_list = ", ".join(f"'{u}'" for u in qc_urls)

    con.execute(f"""
        CREATE TABLE qc_data AS
        SELECT tag, status, asset_name, subject_id, timestamp
        FROM read_parquet([{qc_url_list}], union_by_name=true)
    """)

    sql = f"""
    WITH platform_assets AS (
        SELECT name AS asset_name,
               subject_id,
               COALESCE(instrument_id, '(unknown)') AS instrument_id,
               COALESCE(experimenters, '(unknown)') AS experimenters,
               acquisition_start_time AS timestamp
        FROM asset_basics
        WHERE {PLATFORM_FILTERS_SQL[platform]}
    ),
    unnested AS (
        SELECT asset_name,
               subject_id,
               instrument_id,
               TRIM(exp) AS experimenter,
               timestamp
        FROM platform_assets,
             UNNEST(STRING_SPLIT(experimenters, ',')) AS t(exp)
    )
    SELECT u.asset_name,
           u.subject_id,
           u.instrument_id,
           u.experimenter,
           q.tag,
           q.status,
           u.timestamp
    FROM unnested u
    JOIN qc_data q ON q.asset_name = u.asset_name
    ORDER BY u.timestamp DESC, u.asset_name, q.tag
    """

    df = con.execute(sql).fetchdf()
    con.close()
    return df


def _build_memory(platform: str) -> pd.DataFrame:
    """Build platform QC by iterating over cached per-subject tag status DataFrames."""
    from zombie_squirrel.acorn_helpers.asset_basics import asset_basics

    basics_df = asset_basics()
    platform_df = _filter_basics_pandas(basics_df, platform)
    if platform_df.empty:
        return pd.DataFrame()

    subject_ids = platform_df["subject_id"].dropna().unique()
    all_qc: list[pd.DataFrame] = []
    for subject_id in subject_ids:
        tag_df = acorns.TREE.scurry(f"qc_tag_status/{subject_id}")
        if not tag_df.empty:
            all_qc.append(tag_df)

    if not all_qc:
        return pd.DataFrame()

    qc_combined = pd.concat(all_qc, ignore_index=True)

    basics_sub = platform_df[["name", "subject_id", "instrument_id", "experimenters"]].rename(
        columns={"name": "asset_name"}
    ).copy()

    merged = qc_combined.merge(basics_sub, on=["asset_name", "subject_id"], how="inner")
    merged["instrument_id"] = merged["instrument_id"].fillna("(unknown)")
    merged["experimenters"] = merged["experimenters"].fillna("(unknown)").replace("", "(unknown)")

    rows = []
    for _, row in merged.iterrows():
        for exp in str(row["experimenters"]).split(","):
            r = row.to_dict()
            r["experimenter"] = exp.strip()
            rows.append(r)

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    result = result.drop(columns=["experimenters"])
    cols = ["asset_name", "subject_id", "instrument_id", "experimenter", "tag", "status", "timestamp"]
    return result[[c for c in cols if c in result.columns]]
