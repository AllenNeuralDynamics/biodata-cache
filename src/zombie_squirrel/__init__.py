"""Zombie-squirrel: caching and synchronization for AIND metadata.

Provides functions to fetch and cache project names, subject IDs, and asset
metadata from the AIND metadata database with support for multiple backends.
Also exposes get_squirrel_info to retrieve the squirrel.json registry of all
available acorns and their metadata.
"""

__version__ = "0.29.0"

from zombie_squirrel.acorn_helpers.asset_basics import asset_basics  # noqa: F401
from zombie_squirrel.acorn_helpers.foraging.session import foraging_session  # noqa: F401
from zombie_squirrel.acorn_helpers.foraging.query import (  # noqa: F401
    select_sessions,
    fetch_trials,
    fetch_events,
    read_trials,
    read_events,
)
from zombie_squirrel.acorn_helpers.assets_smartspim import assets_smartspim  # noqa: F401
from zombie_squirrel.acorn_helpers.behavior_curriculum import behavior_curriculum  # noqa: F401
from zombie_squirrel.acorn_helpers.platform_fib import platform_fib  # noqa: F401
from zombie_squirrel.acorn_helpers.platform_qc import platform_qc  # noqa: F401
from zombie_squirrel.acorn_helpers.custom import custom  # noqa: F401
from zombie_squirrel.acorn_helpers.metadata_upgrade import metadata_upgrade  # noqa: F401
from zombie_squirrel.acorn_helpers.qc import qc, qc_columns  # noqa: F401
from zombie_squirrel.acorn_helpers.raw_to_derived import raw_to_derived  # noqa: F401
from zombie_squirrel.acorn_helpers.source_data import source_data  # noqa: F401
from zombie_squirrel.acorn_helpers.unique_project_names import (  # noqa: F401
    unique_project_names,
)
from zombie_squirrel.acorn_helpers.unique_genotypes import (  # noqa: F401
    unique_genotypes,
)
from zombie_squirrel.acorn_helpers.unique_subject_ids import (  # noqa: F401
    unique_subject_ids,
)
from zombie_squirrel.utils import get_squirrel_info  # noqa: F401
