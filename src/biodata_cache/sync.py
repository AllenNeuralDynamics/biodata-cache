"""Synchronization utilities for updating all cached data."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .cache_table_helpers.asset_basics import asset_basics_columns
from .cache_table_helpers.behavior_curriculum import behavior_curriculum_columns
from .cache_table_helpers.metadata_upgrade import metadata_upgrade_columns
from .cache_table_helpers.platform_df import (
    platform_dynamic_foraging_events_columns,
    platform_dynamic_foraging_sessions_columns,
    platform_dynamic_foraging_trials_columns,
)
from .cache_table_helpers.platform_exaspim import platform_exaspim_columns
from .cache_table_helpers.platform_fib import platform_fib_columns
from .cache_table_helpers.platform_mouselight import platform_mouselight_columns
from .cache_table_helpers.platform_qc import PLATFORMS, platform_qc_columns
from .cache_table_helpers.platform_smartspim import assets_smartspim_columns
from .cache_table_helpers.qc import qc_columns
from .cache_table_helpers.scientist.scientist_rl_fib import scientist_rl_fib_columns
from .cache_table_helpers.source_data import source_data_columns
from .cache_table_helpers.time_to_qc import time_to_qc_columns
from .cache_table_helpers.unique_genotypes import unique_genotypes_columns
from .cache_table_helpers.unique_project_names import unique_project_names_columns
from .cache_table_helpers.unique_subject_ids import unique_subject_ids_columns
from .models import CacheRegistry, CacheTable, CacheTableType
from .registry import BACKEND, NAMES, TABLE_REGISTRY


def publish_cache_registry() -> None:
    """Build and publish the cache registry JSON to the cache root.

    Collects column and location information for all registered cache tables,
    constructs a CacheRegistry model, and writes it as JSON via the active Backend.
    """
    table_list = [
        CacheTable(
            name=NAMES["upn"],
            description="Unique project names across all assets",
            location=BACKEND.get_location(NAMES["upn"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=unique_project_names_columns(),
        ),
        CacheTable(
            name=NAMES["usi"],
            description="Unique subject_ids across all assets",
            location=BACKEND.get_location(NAMES["usi"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=unique_subject_ids_columns(),
        ),
        CacheTable(
            name=NAMES["ugt"],
            description="Unique genotypes across all assets where subject.subject_details.genotype is present",
            location=BACKEND.get_location(NAMES["ugt"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=unique_genotypes_columns(),
        ),
        CacheTable(
            name=NAMES["basics"],
            description="Commonly used asset metadata, one row per data asset",
            location=BACKEND.get_location(NAMES["basics"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=asset_basics_columns(),
        ),
        CacheTable(
            name=NAMES["d2r"],
            description="Mapping from derived asset names to their source raw asset names",
            location=BACKEND.get_location(NAMES["d2r"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=source_data_columns(),
        ),
        CacheTable(
            name=NAMES["qc"],
            description="Quality control table with one row per QC metric, partitioned by subject_id",
            location=BACKEND.get_location("qc", partitioned=True),
            partitioned=True,
            partition_key="subject_id",
            type=CacheTableType.asset,
            columns=qc_columns(),
        ),
        CacheTable(
            name=NAMES["smartspim"],
            description="SmartSPIM assets including processing status and neuroglancer links",
            location=BACKEND.get_location(NAMES["smartspim"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=assets_smartspim_columns(),
        ),
        CacheTable(
            name=NAMES["exaspim"],
            description="ExaSPIM assets including processing status and neuroglancer links",
            location=BACKEND.get_location(NAMES["exaspim"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=platform_exaspim_columns(),
        ),
        CacheTable(
            name=NAMES["upgrade"],
            description="Metadata upgrade status for each asset across versions",
            location=BACKEND.get_location(NAMES["upgrade"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=metadata_upgrade_columns(),
        ),
        CacheTable(
            name=NAMES["fib"],
            description="Fiber photometry assets with per-fiber targeted structure and intended channel measurement",
            location=BACKEND.get_location(NAMES["fib"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=platform_fib_columns(),
        ),
        CacheTable(
            name=NAMES["df_sessions"],
            description="Dynamic foraging session table (one row per session); mirrors upstream aind-dynamic-foraging-database",
            location=BACKEND.get_location(NAMES["df_sessions"]),
            partitioned=False,
            type=CacheTableType.platform,
            columns=platform_dynamic_foraging_sessions_columns(),
        ),
        CacheTable(
            name=NAMES["df_trials"],
            description="Dynamic foraging trial table (one row per trial), partitioned by subject_id; mirrors upstream aind-dynamic-foraging-database",
            location=BACKEND.get_location(NAMES["df_trials"], partitioned=True),
            partitioned=True,
            partition_key="subject_id",
            type=CacheTableType.platform,
            columns=platform_dynamic_foraging_trials_columns(),
        ),
        CacheTable(
            name=NAMES["df_events"],
            description="Dynamic foraging event table (one row per behavioral event), partitioned by subject_id; mirrors upstream aind-dynamic-foraging-database",
            location=BACKEND.get_location(NAMES["df_events"], partitioned=True),
            partitioned=True,
            partition_key="subject_id",
            type=CacheTableType.platform,
            columns=platform_dynamic_foraging_events_columns(),
        ),
        CacheTable(
            name=NAMES["curriculum"],
            description="Behavior assets with curriculum name and stage from trainer_state.json",
            location=BACKEND.get_location(NAMES["curriculum"]),
            partitioned=False,
            type=CacheTableType.asset,
            columns=behavior_curriculum_columns(),
        ),
        CacheTable(
            name=NAMES["platform_qc"],
            description="Tag-level QC statuses per platform, one row per asset/tag combination",
            location=BACKEND.get_location("platform_qc", partitioned=True),
            partitioned=True,
            partition_key="platform",
            type=CacheTableType.platform,
            columns=platform_qc_columns(),
        ),
        CacheTable(
            name=NAMES["time_to_qc"],
            description="Time from processing completion to QC completion for derived assets",
            location=BACKEND.get_location(NAMES["time_to_qc"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=time_to_qc_columns(),
        ),
        CacheTable(
            name=NAMES["scientist_rl_fib"],
            description="Cohort summary for scientist RL FIB mice: one row per (fiber_targeted_structure, virus) combination",
            location=BACKEND.get_location(NAMES["scientist_rl_fib"]),
            partitioned=False,
            type=CacheTableType.metadata,
            columns=scientist_rl_fib_columns(),
        ),
        CacheTable(
            name=NAMES["mouselight"],
            description="Janelia MouseLight neuron list (one row per neuron) with label, soma region and tracing UUIDs",
            location=BACKEND.get_location(NAMES["mouselight"]),
            partitioned=False,
            type=CacheTableType.platform,
            columns=platform_mouselight_columns(),
        ),
    ]
    registry = CacheRegistry(tables=table_list)
    BACKEND.put_json("cache_registry.json", registry.model_dump_json())


def update_all_tables(fast: bool = True, slow: bool = True) -> None:
    """Trigger force update of registered cache table functions.

    asset_basics always runs first as it is a prerequisite for both sets.
    Fast cache tables (DocDB-only queries) and slow cache tables (per-subject or S3 data)
    can be run independently via the fast/slow flags.
    After all selected updates, publishes cache registry JSON to the cache root.

    Args:
        fast: If True, run fast DocDB-only cache tables (upn, usi, ugt, d2r, upgrade, fib, mouselight, platform_qc).
        slow: If True, run slow per-subject/S3 cache tables (qc, smartspim, exaspim, df_sessions/df_trials/df_events, curriculum, time_to_qc, scientist_rl_fib).
    """
    df_basics = TABLE_REGISTRY[NAMES["basics"]](force_update=True)

    if fast:
        TABLE_REGISTRY[NAMES["upn"]](force_update=True)
        TABLE_REGISTRY[NAMES["usi"]](force_update=True)
        TABLE_REGISTRY[NAMES["ugt"]](force_update=True)
        TABLE_REGISTRY[NAMES["d2r"]](force_update=True)
        TABLE_REGISTRY[NAMES["upgrade"]](force_update=True)
        TABLE_REGISTRY[NAMES["fib"]](force_update=True)
        TABLE_REGISTRY[NAMES["mouselight"]](force_update=True)
        for platform in PLATFORMS:
            TABLE_REGISTRY[NAMES["platform_qc"]](platform=platform, force_update=True)

    if slow:
        subject_ids = df_basics["subject_id"].dropna().unique()

        if len(subject_ids) > 0:
            qc_table_fn = TABLE_REGISTRY[NAMES["qc"]]
            try:
                with ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(qc_table_fn, subject_id=subject_id, force_update=True)
                        for subject_id in subject_ids
                    ]
                    for future in as_completed(futures):
                        future.result()
            except Exception:
                for subject_id in subject_ids:
                    qc_table_fn(subject_id=subject_id, force_update=True)

        TABLE_REGISTRY[NAMES["smartspim"]](force_update=True)
        TABLE_REGISTRY[NAMES["exaspim"]](force_update=True)
        df_sessions = TABLE_REGISTRY[NAMES["df_sessions"]](force_update=True)
        df_subject_ids = df_sessions["subject_id"].dropna().unique() if "subject_id" in df_sessions.columns else []
        if len(df_subject_ids) > 0:
            trials_fn = TABLE_REGISTRY[NAMES["df_trials"]]
            events_fn = TABLE_REGISTRY[NAMES["df_events"]]
            try:
                with ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(trials_fn, subject_id=subject_id, force_update=True)
                        for subject_id in df_subject_ids
                    ]
                    futures += [
                        executor.submit(events_fn, subject_id=subject_id, force_update=True)
                        for subject_id in df_subject_ids
                    ]
                    for future in as_completed(futures):
                        future.result()
            except Exception:
                for subject_id in df_subject_ids:
                    trials_fn(subject_id=subject_id, force_update=True)
                    events_fn(subject_id=subject_id, force_update=True)
        TABLE_REGISTRY[NAMES["curriculum"]](force_update=True)
        TABLE_REGISTRY[NAMES["time_to_qc"]](force_update=True)
        TABLE_REGISTRY[NAMES["scientist_rl_fib"]](force_update=True)

    publish_cache_registry()
