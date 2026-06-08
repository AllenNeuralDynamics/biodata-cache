"""Foraging session acorn: one row per foraging session, sourced from the upstream cache."""

import logging

import duckdb
import pandas as pd

import zombie_squirrel.acorns as acorns
from zombie_squirrel.squirrel import Column
from zombie_squirrel.utils import SquirrelMessage, setup_logging

UPSTREAM_SESSION_S3 = "s3://aind-scratch-data/aind-dynamic-foraging-cache/session_table.parquet"
_TABLE_NAME = "foraging/session"


def _add_asset_name(df: pd.DataFrame) -> pd.DataFrame:
    """Derive asset_name from co_s3_nwb_uri for joining with asset_basics."""
    df = df.copy()
    uri = df["co_s3_nwb_uri"].astype(object)  # ensure object dtype so .str works on NaN-only columns
    df["asset_name"] = uri.str.extract(r"/nwb/(.+?)\.nwb$", expand=False)
    return df


def _fetch_upstream() -> pd.DataFrame:
    conn = duckdb.connect()
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    df = conn.sql(f"SELECT * FROM read_parquet('{UPSTREAM_SESSION_S3}')").df()
    return _add_asset_name(df)


@acorns.register_acorn(acorns.NAMES["foraging"])
def foraging_session(force_update: bool = False) -> pd.DataFrame:
    """Return a table of dynamic foraging sessions from the upstream parquet cache.

    Source: s3://aind-scratch-data/aind-dynamic-foraging-cache/session_table.parquet

    Args:
        force_update: If True, bypass cache and re-fetch from upstream S3.

    Returns:
        DataFrame with one row per session. Includes asset_name for joining
        with asset_basics, plus all upstream session metrics and metadata.
    """
    df = acorns.TREE.scurry(_TABLE_NAME)

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch from upstream.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn=acorns.NAMES["foraging"],
                message="Updating cache from upstream S3",
            ).to_json()
        )
        df = _fetch_upstream()
        acorns.TREE.hide(_TABLE_NAME, df)

    return df


def foraging_session_columns() -> list[Column]:
    return [
        Column(name="subject_id", description="Subject/mouse ID"),
        Column(name="session_date", description="Date of the session (YYYY-MM-DD)"),
        Column(name="nwb_suffix", description="NWB time suffix identifying the session file"),
        Column(name="session", description="Session number within the day"),
        Column(name="_session_id", description="Unique session key: subject_id_session_date_nwb_suffix"),
        Column(name="asset_name", description="AIND asset name for joining with asset_basics"),
        Column(name="co_asset_id", description="Code Ocean data asset ID"),
        Column(name="co_s3_nwb_uri", description="S3 URI of the NWB file inside the CO asset"),
        Column(name="nwb_data_source", description="NWB data source: co_asset, bonsai_s3, or bpod_s3"),
        Column(name="rig", description="Rig used for the session"),
        Column(name="trainer", description="Trainer who ran the session"),
        Column(name="PI", description="Principal investigator"),
        Column(name="curriculum_name", description="Auto-training curriculum name"),
        Column(name="curriculum_version", description="Auto-training curriculum version"),
        Column(name="current_stage_actual", description="Actual curriculum stage at session time"),
        Column(name="task", description="Task name"),
        Column(name="session_start_time", description="Session start timestamp"),
        Column(name="session_end_time", description="Session end timestamp"),
        Column(name="session_run_time_in_min", description="Session duration in minutes"),
        Column(name="total_trials", description="Total number of trials"),
        Column(name="finished_trials", description="Number of finished (non-ignored) trials"),
        Column(name="finished_rate", description="Fraction of trials that were finished"),
        Column(name="foraging_eff", description="Foraging efficiency metric"),
        Column(name="foraging_eff_random_seed", description="Foraging efficiency with random seed baseline"),
        Column(name="bias_naive", description="Naive side bias estimate"),
        Column(name="reaction_time_median", description="Median reaction time in seconds"),
        Column(name="early_lick_rate", description="Rate of early lick trials"),
    ]
