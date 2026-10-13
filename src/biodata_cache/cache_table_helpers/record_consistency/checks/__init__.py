"""Record-consistency checks, one per module; the module name is the check key."""

from biodata_cache.cache_table_helpers.record_consistency.checks import (  # noqa: F401
    docdb_duplicate_name_v2,
    docdb_v1_name_missing_in_v2,
)
