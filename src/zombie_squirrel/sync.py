"""Synchronization utilities for updating all cached data."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .acorn_helpers.asset_basics import asset_basics_columns
from .acorn_helpers.assets_smartspim import assets_smartspim_columns
from .acorn_helpers.foraging_sessions import foraging_sessions_columns
from .acorn_helpers.behavior_curriculum import behavior_curriculum_columns
from .acorn_helpers.platform_fib import platform_fib_columns
from .acorn_helpers.platform_qc import platform_qc_columns, PLATFORMS
from .acorn_helpers.metadata_upgrade import metadata_upgrade_columns
from .acorn_helpers.qc import qc_columns
from .acorn_helpers.source_data import source_data_columns
from .acorn_helpers.unique_genotypes import unique_genotypes_columns
from .acorn_helpers.unique_project_names import unique_project_names_columns
from .acorn_helpers.unique_subject_ids import unique_subject_ids_columns
from .acorns import ACORN_REGISTRY, NAMES, TREE
from .squirrel import Acorn, AcornType, Squirrel


def publish_squirrel_metadata() -> None:
    """Build and publish a Squirrel metadata JSON to the cache root.

    Collects column and location information for all registered acorns,
    constructs a Squirrel model, and writes it as JSON via the active Tree.
    """
    acorn_list = [
        Acorn(
            name=NAMES["upn"],
            description="Unique project names across all assets",
            location=TREE.get_location(NAMES["upn"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=unique_project_names_columns(),
        ),
        Acorn(
            name=NAMES["usi"],
            description="Unique subject_ids across all assets",
            location=TREE.get_location(NAMES["usi"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=unique_subject_ids_columns(),
        ),
        Acorn(
            name=NAMES["ugt"],
            description="Unique genotypes across all assets where subject.subject_details.genotype is present",
            location=TREE.get_location(NAMES["ugt"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=unique_genotypes_columns(),
        ),
        Acorn(
            name=NAMES["basics"],
            description="Commonly used asset metadata, one row per data asset",
            location=TREE.get_location(NAMES["basics"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=asset_basics_columns(),
        ),
        Acorn(
            name=NAMES["d2r"],
            description="Mapping from derived asset names to their source raw asset names",
            location=TREE.get_location(NAMES["d2r"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=source_data_columns(),
        ),
        Acorn(
            name=NAMES["qc"],
            description="Quality control table with one row per QC metric, partitioned by subject_id",
            location=TREE.get_location("qc", partitioned=True),
            partitioned=True,
            partition_key="subject_id",
            type=AcornType.asset,
            columns=qc_columns(),
        ),
        Acorn(
            name=NAMES["smartspim"],
            description="SmartSPIM assets including processing status and neuroglancer links",
            location=TREE.get_location(NAMES["smartspim"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=assets_smartspim_columns(),
        ),
        Acorn(
            name=NAMES["upgrade"],
            description="Metadata upgrade status for each asset across versions",
            location=TREE.get_location(NAMES["upgrade"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=metadata_upgrade_columns(),
        ),
        Acorn(
            name=NAMES["fib"],
            description="Fiber photometry assets with per-fiber targeted structure and intended channel measurement",
            location=TREE.get_location(NAMES["fib"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=platform_fib_columns(),
        ),
        Acorn(
            name=NAMES["foraging"],
            description="Foraging behavior sessions with key performance metrics, one row per session",
            location=TREE.get_location(NAMES["foraging"]),
            partitioned=False,
            type=AcornType.metadata,
            columns=foraging_sessions_columns(),
        ),
        Acorn(
            name=NAMES["curriculum"],
            description="Behavior assets with curriculum name and stage from trainer_state.json",
            location=TREE.get_location(NAMES["curriculum"]),
            partitioned=False,
            type=AcornType.asset,
            columns=behavior_curriculum_columns(),
        ),
        Acorn(
            name=NAMES["platform_qc"],
            description="Tag-level QC statuses per platform, one row per asset/tag combination",
            location=TREE.get_location("platform_qc", partitioned=True),
            partitioned=True,
            partition_key="platform",
            type=AcornType.platform,
            columns=platform_qc_columns(),
        ),
    ]
    squirrel = Squirrel(acorns=acorn_list)
    TREE.plant("squirrel.json", squirrel.model_dump_json())


def hide_acorns():
    """Trigger force update of all registered acorn functions.

    Updates each acorn individually. For the QC acorn, fetches
    unique subject IDs from asset_basics and updates each individually,
    using parallelization when multiple subjects are available.
    After all updates, publishes Squirrel metadata JSON to the cache root.
    """
    ACORN_REGISTRY[NAMES["upn"]](force_update=True)
    ACORN_REGISTRY[NAMES["usi"]](force_update=True)
    ACORN_REGISTRY[NAMES["ugt"]](force_update=True)

    df_basics = ACORN_REGISTRY[NAMES["basics"]](force_update=True)

    ACORN_REGISTRY[NAMES["d2r"]](force_update=True)
    ACORN_REGISTRY[NAMES["upgrade"]](force_update=True)

    subject_ids = df_basics["subject_id"].dropna().unique()

    if len(subject_ids) > 0:
        qc_acorn = ACORN_REGISTRY[NAMES["qc"]]
        try:
            with ThreadPoolExecutor() as executor:
                futures = [
                    executor.submit(qc_acorn, subject_id=subject_id, force_update=True) for subject_id in subject_ids
                ]
                for future in as_completed(futures):
                    future.result()
        except Exception:
            for subject_id in subject_ids:
                qc_acorn(subject_id=subject_id, force_update=True)

    ACORN_REGISTRY[NAMES["smartspim"]](force_update=True)
    ACORN_REGISTRY[NAMES["fib"]](force_update=True)
    ACORN_REGISTRY[NAMES["foraging"]](force_update=True)
    ACORN_REGISTRY[NAMES["curriculum"]](force_update=True)

    for platform in PLATFORMS:
        ACORN_REGISTRY[NAMES["platform_qc"]](platform=platform, force_update=True)

    publish_squirrel_metadata()
