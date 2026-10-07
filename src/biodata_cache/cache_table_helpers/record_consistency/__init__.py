"""Record-consistency cache tables: a snapshot of live consistency state.

Add a check by adding a module under ``checks/`` that subclasses ``Check`` and
importing it in ``checks/__init__.py``. Add a source in ``sources.py``. See the
``record-consistency`` skill for concepts, rules, and design decisions.
"""

from biodata_cache.cache_table_helpers.record_consistency import checks, sources  # noqa: F401
from biodata_cache.cache_table_helpers.record_consistency.framework import (  # noqa: F401
    record_consistency_checks,
    record_consistency_checks_columns,
    record_consistency_results,
    record_consistency_results_columns,
)
