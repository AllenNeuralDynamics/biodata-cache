"""Foraging sessions acorn: one row per behavior session from df_sessions.pkl."""

import io
import logging

import boto3
import pandas as pd

import zombie_squirrel.acorns as acorns
from zombie_squirrel.squirrel import Column
from zombie_squirrel.utils import SquirrelMessage, setup_logging

_SOURCE_BUCKET = "aind-behavior-data"
_SOURCE_KEY = "foraging_nwb_bonsai_processed/df_sessions.pkl"

_COLUMN_MAP = {
    ("metadata", "rig"): "rig",
    ("metadata", "user_name"): "trainer",
    ("metadata", "task"): "task",
    ("auto_train", "curriculum_name"): "curriculum_name",
    ("auto_train", "curriculum_version"): "curriculum_version",
    ("auto_train", "current_stage_actual"): "current_stage_actual",
    ("session_stats", "foraging_eff"): "foraging_eff",
    ("session_stats", "foraging_eff_random_seed"): "foraging_eff_random_seed",
    ("session_stats", "finished_trials"): "finished_trials",
    ("session_stats", "finished_rate"): "finished_rate",
    ("session_stats", "total_trials"): "total_trials",
    ("session_stats", "bias_naive"): "bias_naive",
}


def _fetch_foraging_sessions() -> pd.DataFrame:
    """Download df_sessions.pkl from S3 and return a flattened DataFrame."""
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=_SOURCE_BUCKET, Key=_SOURCE_KEY)
    raw = pd.read_pickle(io.BytesIO(obj["Body"].read()))

    # Extract row-index levels into a plain dict — avoids reset_index() which
    # pads them into the MultiIndex column structure as ('subject_id', '') etc.,
    # causing to_parquet() to write tuple-string column names that DuckDB can't use.
    idx = raw.index.to_frame(index=False)
    data = {
        "subject_id": idx["subject_id"],
        "session_date": idx["session_date"].astype(str),
        "session": idx["session"],
        "nwb_suffix": idx["nwb_suffix"],
    }
    for src_col, dest_col in _COLUMN_MAP.items():
        data[dest_col] = raw[src_col].values

    return pd.DataFrame(data)


@acorns.register_acorn(acorns.NAMES["foraging"])
def foraging_sessions(force_update: bool = False) -> pd.DataFrame:
    """Return a flattened table of foraging behavior sessions.

    Source: s3://aind-behavior-data/foraging_nwb_bonsai_processed/df_sessions.pkl

    Args:
        force_update: If True, bypass cache and rebuild from source pkl.

    Returns:
        DataFrame with one row per session and the columns listed in
        foraging_sessions_columns().
    """
    df = acorns.TREE.scurry(acorns.NAMES["foraging"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from source.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn=acorns.NAMES["foraging"],
                message="Updating cache from S3 pkl",
            ).to_json()
        )

        df = _fetch_foraging_sessions()
        acorns.TREE.hide(acorns.NAMES["foraging"], df)

    return df


def foraging_sessions_columns() -> list[Column]:
    """Return foraging_sessions acorn column definitions."""
    return [
        Column(name="subject_id", description="Subject/mouse ID"),
        Column(name="session_date", description="Date of the session (YYYY-MM-DD)"),
        Column(name="session", description="Session number within the day"),
        Column(name="nwb_suffix", description="NWB file suffix identifying the session file"),
        Column(name="rig", description="Rig/apparatus used for the session"),
        Column(name="trainer", description="User/trainer who ran the session"),
        Column(name="task", description="Task name (e.g. Coupled Baiting)"),
        Column(name="curriculum_name", description="Auto-training curriculum name"),
        Column(name="curriculum_version", description="Auto-training curriculum version"),
        Column(name="current_stage_actual", description="Actual training stage at time of session"),
        Column(name="foraging_eff", description="Foraging efficiency (fraction of optimal reward collected)"),
        Column(name="foraging_eff_random_seed", description="Foraging efficiency relative to random-seed baseline"),
        Column(name="finished_trials", description="Number of finished (non-ignored) trials"),
        Column(name="finished_rate", description="Fraction of trials that were finished"),
        Column(name="total_trials", description="Total number of trials in the session"),
        Column(name="bias_naive", description="Naive lick-side bias estimate"),
    ]
