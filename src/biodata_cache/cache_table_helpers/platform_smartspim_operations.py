"""SmartSPIM processing-status cache table (partitioned by asset_name).

Reconstructs the processing lifecycle of each SmartSPIM acquisition from
the structured pipeline logs emitted to CloudWatch by the
``SmartSPIM Pipeline``. One row is stored per lifecycle event (``pipeline_plan``
/ ``stage_start`` / ``stage_complete`` / ``stage_failure`` / ``pipeline_finished``);
``asset_name`` (the raw acquisition name) is the partition key and joins to
``asset_basics``.

Unlike the other operations pipelines, SmartSPIM logs the asset under
``dataset_name``, the failure message under ``error``, and failures as
``stage_failure`` (stored as ``stage_error`` to match the other tables). Legacy records logged
under a channel name (``Ex_*``) or the derived stitched asset name are excluded.

The CloudWatch log processing is shared with the other ``*_operations`` tables in
``shared.cloudwatch_utils``; this module only pins the pipeline name and its log
schema.
"""

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.shared import cloudwatch_utils as cw
from biodata_cache.models import Column

_PIPELINE_NAME = "SmartSPIM Pipeline"
_TABLE_KEY = "smartspim_operations"
_LOG_SCHEMA = cw.PipelineLogSchema(
    asset_field="dataset_name",
    event_types=("pipeline_plan", "stage_start", "stage_complete", "stage_failure", "pipeline_finished"),
    error_field="error",
    # Legacy rows: old logs used channel names, or the derived stitched asset name.
    exclude_asset_patterns=("^Ex_", "_stitched_"),
    # Match the other operations tables. pipeline_plan / pipeline_finished are
    # run-level events with no stage equivalent, so they are kept as-is.
    event_type_aliases=(("stage_failure", "stage_error"),),
)

cw.register_operations_pipeline(_PIPELINE_NAME, _TABLE_KEY, _LOG_SCHEMA)


def fetch_all_smartspim_operations(lookback_days: int = cw.DEFAULT_LOOKBACK_DAYS) -> list[str]:
    """Incrementally fetch this pipeline's events and append/write all partitions."""
    return cw.fetch_all_operations(_TABLE_KEY, _PIPELINE_NAME, lookback_days)


@registry.register_table(registry.NAMES["smartspim_operations"])
def platform_smartspim_operations(
    asset_name: str | None = None,
    force_update: bool = False,
    lazy: bool = False,
    location: str | None = None,
) -> pd.DataFrame | str:
    """Return SmartSPIM processing events, or rebuild the whole table.

    One row per pipeline lifecycle event (``pipeline_plan`` / ``stage_start`` /
    ``stage_complete`` / ``stage_error`` / ``pipeline_finished``) found in the
    CloudWatch pipeline logs, across every pipeline
    stage (``process_name``). Data is cached per asset_name partition. Group by
    asset_name for a per-acquisition processing-status view.

    A ``force_update`` with no ``asset_name`` rebuilds every partition from a single
    bulk CloudWatch query (the normal sync path); this table is not built one asset
    at a time. Passing ``asset_name`` targets a single acquisition (ad-hoc refresh
    or read).

    Args:
        asset_name: Acquisition name to read/refresh (joins to asset_basics
            ``name``). If None, a ``force_update`` rebuilds the whole table and a
            read is not supported.
        force_update: If True, re-query CloudWatch and write the cache (the whole
            table when ``asset_name`` is None, otherwise just that acquisition). An
            empty DataFrame is returned; read again without force_update.
        lazy: If True, return the partition's storage location string (for DuckDB)
            instead of loading the DataFrame. Requires ``asset_name``.
        location: Unused; accepted for a uniform sync interface.

    Returns:
        DataFrame of processing events; the partition location string if lazy=True;
        or an empty DataFrame if force_update=True (data is written to the cache).

    Raises:
        ValueError: If ``asset_name`` is None on a read, or the cache is empty for
            the asset and force_update is False.
    """
    return cw.platform_operations(_TABLE_KEY, _PIPELINE_NAME, asset_name, force_update, lazy)


def platform_smartspim_operations_columns() -> list[Column]:
    """Return platform_smartspim_operations cache table column definitions."""
    return cw.operations_columns()
