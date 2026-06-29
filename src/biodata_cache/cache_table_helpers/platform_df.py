"""Platform dynamic foraging cache tables.

Mirrors the layout of the upstream `aind-dynamic-foraging-database` parquet
database (one session table + hive-partitioned trial/event tables) inside the
biodata-cache backend. The upstream package is the source of truth for the
underlying parquet files; these helpers read it via DuckDB and re-publish the
data into our cache version folder so the same data is reachable through the
biodata-cache backend abstraction.
"""

import logging

import duckdb
import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging


def _log(table: str, message: str) -> None:
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=table,
            message=message,
        ).to_json()
    )


def _read_session_table() -> pd.DataFrame:
    from aind_dynamic_foraging_database import SESSION_DB
    with duckdb.connect() as con:
        return con.sql(f"SELECT * FROM read_parquet('{SESSION_DB}')").df()


def _read_subject_partition(base: str, subject_id: str) -> pd.DataFrame:
    query = (
        f"SELECT * FROM read_parquet("
        f"'{base}/subject_id={subject_id}/*.parquet', "
        f"hive_partitioning=true, union_by_name=true)"
    )
    with duckdb.connect() as con:
        return con.sql(query).df()


@registry.register_table(registry.NAMES["df_sessions"])
def platform_dynamic_foraging_sessions(force_update: bool = False) -> pd.DataFrame:
    """Return the dynamic foraging session table (one row per session).

    Mirrors `session_table.parquet` from the upstream
    `aind-dynamic-foraging-database` package. Data is read via DuckDB from the
    upstream `SESSION_DB` path and written to our cache backend.

    Args:
        force_update: If True, bypass cache and fetch fresh data from upstream.

    Returns:
        DataFrame with one row per session, columns as documented upstream.
    """
    table = registry.NAMES["df_sessions"]
    df = registry.BACKEND.read(table)

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from upstream database.")

    if df.empty or force_update:
        setup_logging()
        _log(table, "Updating cache from aind-dynamic-foraging-database session_table")
        df = _read_session_table()
        registry.BACKEND.write(table, df)

    return df


@registry.register_table(registry.NAMES["df_trials"])
def platform_dynamic_foraging_trials(subject_id: str, force_update: bool = False) -> pd.DataFrame:
    """Return the dynamic foraging trial rows for a single subject.

    Mirrors `trial_table/subject_id=<id>/...parquet` from the upstream
    `aind-dynamic-foraging-database` package. Data is read via DuckDB from the
    upstream `TRIAL_DB` partition for the given subject and written to our
    cache backend (one partition per subject).

    Args:
        subject_id: Subject ID whose trial partition to fetch.
        force_update: If True, bypass cache and fetch fresh data from upstream.

    Returns:
        DataFrame with one row per trial for the subject.
    """
    table = registry.NAMES["df_trials"]
    cache_key = f"{table}/{subject_id}"
    df = registry.BACKEND.read(cache_key)

    if df.empty and not force_update:
        raise ValueError(
            f"Cache is empty for subject {subject_id}. Use force_update=True to fetch data from upstream."
        )

    if df.empty or force_update:
        setup_logging()
        from aind_dynamic_foraging_database import TRIAL_DB
        _log(table, f"Updating cache for subject {subject_id} from upstream trial_table")
        df = _read_subject_partition(TRIAL_DB, str(subject_id))
        registry.BACKEND.write(cache_key, df)

    return df


@registry.register_table(registry.NAMES["df_events"])
def platform_dynamic_foraging_events(subject_id: str, force_update: bool = False) -> pd.DataFrame:
    """Return the dynamic foraging event rows for a single subject.

    Mirrors `event_table/subject_id=<id>/...parquet` from the upstream
    `aind-dynamic-foraging-database` package. Data is read via DuckDB from the
    upstream `EVENT_DB` partition for the given subject and written to our
    cache backend (one partition per subject).

    Args:
        subject_id: Subject ID whose event partition to fetch.
        force_update: If True, bypass cache and fetch fresh data from upstream.

    Returns:
        DataFrame with one row per behavioral event for the subject.
    """
    table = registry.NAMES["df_events"]
    cache_key = f"{table}/{subject_id}"
    df = registry.BACKEND.read(cache_key)

    if df.empty and not force_update:
        raise ValueError(
            f"Cache is empty for subject {subject_id}. Use force_update=True to fetch data from upstream."
        )

    if df.empty or force_update:
        setup_logging()
        from aind_dynamic_foraging_database import EVENT_DB
        _log(table, f"Updating cache for subject {subject_id} from upstream event_table")
        df = _read_subject_partition(EVENT_DB, str(subject_id))
        registry.BACKEND.write(cache_key, df)

    return df


def platform_dynamic_foraging_sessions_columns() -> list[Column]:
    """Return key column definitions for the dynamic foraging session table.

    Lists the documented key columns from the upstream schema (the full table
    has ~160 columns). Use DuckDB DESCRIBE against the parquet for the full
    list.
    """
    return [
        Column(name="_session_id", description="Session key (= subject_id_session-date_nwb-suffix); joins to trial/event session_id"),
        Column(name="subject_id", description="Mouse ID (string)"),
        Column(name="session_date", description="YYYY-MM-DD"),
        Column(name="nwb_suffix", description="Session start HHMMSS as int (disambiguates same-day sessions)"),
        Column(name="task", description="e.g. Uncoupled Baiting, Coupled Baiting, Uncoupled Without Baiting"),
        Column(name="total_trials", description="Foraging trials, autowater excluded"),
        Column(name="total_trials_with_autowater", description="All trials (= trial-table COUNT(*))"),
        Column(name="finished_trials", description="Non-ignored foraging trials"),
        Column(name="ignored_trials", description="Foraging trials with no response"),
        Column(name="finished_rate", description="Finished fraction"),
        Column(name="ignore_rate", description="Ignored fraction"),
        Column(name="reward_trials", description="Earned (non-autowater) rewards"),
        Column(name="reward_rate", description="reward / finished"),
        Column(name="foraging_eff", description="Foraging efficiency vs ideal"),
        Column(name="foraging_performance", description="foraging_eff x finished_rate"),
        Column(name="bias_naive", description="Side bias, -1 (left) ... +1 (right)"),
        Column(name="autowater_collected", description="Autowater trials collected"),
        Column(name="autowater_ignored", description="Autowater trials ignored"),
        Column(name="reaction_time_median", description="Median reaction time"),
        Column(name="early_lick_rate", description="Early lick rate"),
        Column(name="institute", description="High-level grouping: AIND or Janelia"),
        Column(name="hardware", description="bonsai or bpod"),
        Column(name="rig_type", description="training or ephys"),
        Column(name="room", description="Rig room (447, 446, 347, ...)"),
        Column(name="data_source", description="Fine-grained composite: {institute}_{rig_type}_{room}_{hardware}"),
        Column(name="curriculum_name", description="Curriculum name; 'None' = off-curriculum, NULL = not in Han"),
        Column(name="curriculum_version", description="Curriculum version; 'None' = off-curriculum"),
        Column(name="current_stage_actual", description="Curriculum stage reached (STAGE_1_WARMUP ... STAGE_FINAL/GRADUATED)"),
        Column(name="rig", description="Rig name"),
        Column(name="trainer", description="Session trainer"),
        Column(name="PI", description="Principal Investigator"),
        Column(name="weight_after", description="Mouse weight after session"),
        Column(name="water_in_session_total", description="Total water delivered in session"),
        Column(name="nwb_data_source", description="co_asset | bonsai_s3 | bpod_s3 (build provenance, not a science filter)"),
        Column(name="co_asset_id", description="Code Ocean asset id (NULL if none)"),
        Column(name="co_s3_nwb_uri", description="Code Ocean NWB S3 URI (NULL if none)"),
    ]


def platform_dynamic_foraging_trials_columns() -> list[Column]:
    """Return key column definitions for the dynamic foraging trial table.

    Lists the documented key columns from the upstream schema (the full table
    has 103 columns). Use DuckDB DESCRIBE against the parquet for the full
    list.
    """
    return [
        Column(name="session_id", description="Join key -> session _session_id"),
        Column(name="subject_id", description="Mouse ID (BIGINT in partition column; cast to VARCHAR when filtering)"),
        Column(name="session_date", description="YYYY-MM-DD"),
        Column(name="nwb_suffix", description="Session suffix"),
        Column(name="trial", description="Trial index within the session"),
        Column(name="animal_response", description="0 = lick left, 1 = lick right, 2 = ignore (no response)"),
        Column(name="earned_reward", description="Earned a non-autowater reward (= rewarded_historyL OR rewarded_historyR)"),
        Column(name="rewarded_historyL", description="Reward delivered on left"),
        Column(name="rewarded_historyR", description="Reward delivered on right"),
        Column(name="reward_probabilityL", description="Scheduled reward probability for left side"),
        Column(name="reward_probabilityR", description="Scheduled reward probability for right side"),
        Column(name="auto_waterL", description="Autowater given on left (non-autowater trial = 0)"),
        Column(name="auto_waterR", description="Autowater given on right (non-autowater trial = 0)"),
        Column(name="reward_random_number_left", description="Draw used for baiting (left)"),
        Column(name="reward_random_number_right", description="Draw used for baiting (right)"),
        Column(name="goCue_start_time_in_session", description="Go-cue time (s from session start)"),
        Column(name="choice_time_in_session", description="Choice (lick) time (s)"),
        Column(name="reward_time_in_session", description="Reward time (s)"),
        Column(name="reaction_time", description="choice - go-cue (s)"),
        Column(name="nwb_data_source", description="NWB reader source"),
    ]


def platform_dynamic_foraging_events_columns() -> list[Column]:
    """Return the dynamic foraging event table column definitions (all 10)."""
    return [
        Column(name="session_id", description="Join key -> session _session_id"),
        Column(name="subject_id", description="Mouse ID (BIGINT in partition column; cast to VARCHAR when filtering)"),
        Column(name="session_date", description="YYYY-MM-DD"),
        Column(name="nwb_suffix", description="Session suffix"),
        Column(name="trial", description="Trial index this event falls in (-1 before first go-cue)"),
        Column(name="timestamps", description="Event time, s from session start"),
        Column(name="raw_timestamps", description="Original NWB timestamp (un-aligned)"),
        Column(
            name="event",
            description=(
                "One of: goCue_start_time, left_lick_time, right_lick_time, "
                "left_reward_delivery_time, right_reward_delivery_time, optogenetics_time"
            ),
        ),
        Column(name="data", description="Event payload (string-normalized)"),
        Column(name="nwb_data_source", description="NWB reader source"),
    ]
