"""Shared CloudWatch pipeline-log processing for ``*_operations`` cache tables.

Several platform ``*_operations`` tables reconstruct the processing lifecycle of an
acquisition from the structured pipeline logs emitted to CloudWatch. Each log
record is a JSON document carrying the acquisition it belongs to, the pipeline
stage (``process_name``), and an ``event_type`` (``stage_start`` / ``stage_complete``
/ ``stage_error``). One row is stored per lifecycle event; ``asset_name`` (the
acquisition name) is the partition key and joins to ``asset_basics``.

A single CloudWatch Logs Insights query fetches every event across all
acquisitions in a lookback window; the events are then grouped locally and one
partition is written per acquisition. This is far cheaper than one query per
asset (each Insights query scans the whole log group).

These functions are parameterized by the pipeline name and the table's registry
key so that a table module only needs to supply those two values.
"""

import json
import logging
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

import boto3
import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

LOG_GROUP = "/codeocean/pipelines"
KEEP_EVENT_TYPES = ("stage_start", "stage_complete", "stage_error")
DEFAULT_LOOKBACK_DAYS = 400
# CloudWatch Logs Insights returns at most 10000 rows per query; when a time
# window hits this cap it is split in half and re-queried so no events are lost.
MAX_QUERY_RESULTS = 10000
QUERY_POLL_SECONDS = 2.0
QUERY_TIMEOUT_SECONDS = 120.0
REGION = "us-west-2"

# Registry of operations pipelines, populated at import time by each
# ``platform_*_operations`` module via ``register_operations_pipeline``. Maps the
# CloudWatch ``pipeline_name`` to the operations table's registry key. The single
# ``operations`` sync job pulls every registered pipeline's events in one query and
# routes each event to the matching table.
_OPERATIONS_PIPELINES: dict[str, str] = {}


@dataclass(frozen=True)
class PipelineLogSchema:
    """How a pipeline's structured log records are shaped.

    Pipelines do not all log the same fields. The default matches the fiber
    photometry and dynamic foraging pipelines; others override it at registration.

    Attributes:
        asset_field: Record field holding the asset name (the partition key).
        event_types: Lifecycle ``event_type`` values to keep.
        error_field: Record field holding the error/traceback for failure events.
        exclude_asset_patterns: Logs Insights regexes; records whose asset field
            matches any of them are dropped (e.g. legacy rows logged under another
            name).
        event_type_aliases: Maps this pipeline's raw ``event_type`` values to the
            shared vocabulary (e.g. ``stage_failure`` -> ``stage_error``) so every
            operations table reports the same values. Unmapped values pass through.
    """

    asset_field: str = "acquisition_name"
    event_types: tuple[str, ...] = KEEP_EVENT_TYPES
    error_field: str = "exc_info"
    exclude_asset_patterns: tuple[str, ...] = ()
    event_type_aliases: tuple[tuple[str, str], ...] = ()

    def normalize_event_type(self, event_type: str | None) -> str | None:
        """Return the shared event_type for a raw value from this pipeline."""
        return dict(self.event_type_aliases).get(event_type, event_type)


DEFAULT_LOG_SCHEMA = PipelineLogSchema()

# Per-pipeline log schemas, populated by ``register_operations_pipeline``. Pipelines
# without an entry use ``DEFAULT_LOG_SCHEMA``.
_PIPELINE_SCHEMAS: dict[str, PipelineLogSchema] = {}

EVENT_COLUMNS = [
    "asset_name",
    "pipeline_name",
    "timestamp",
    "ingest_ts",
    "process_name",
    "event_type",
    "level",
    "message",
    "error_info",
    "cloudwatch_url",
]


def register_operations_pipeline(
    pipeline_name: str,
    table_key: str,
    schema: PipelineLogSchema | None = None,
) -> None:
    """Register an operations table's CloudWatch pipeline for the combined pull.

    Pass ``schema`` when the pipeline's log records differ from
    ``DEFAULT_LOG_SCHEMA`` (e.g. a different asset-name field).
    """
    _OPERATIONS_PIPELINES[pipeline_name] = table_key
    if schema is not None:
        _PIPELINE_SCHEMAS[pipeline_name] = schema


def schema_for(pipeline_name: str | None) -> PipelineLogSchema:
    """Return the log schema registered for a pipeline, or the default."""
    return _PIPELINE_SCHEMAS.get(pipeline_name, DEFAULT_LOG_SCHEMA)


def _last_scan_key(scope: str) -> str:
    """Return the sidecar key that records a scan scope's last-seen ingestion time."""
    return f"{scope}_last_scan.json"


def read_last_scan(scope: str) -> datetime | None:
    """Return the UTC datetime of the last successful scan, or None if never scanned.

    The sidecar records the maximum log-ingestion time seen on the previous run so
    the next run only queries newly ingested events. A missing or malformed sidecar
    triggers a full initial scan.
    """
    try:
        raw = registry.BACKEND.get_json(_last_scan_key(scope))
        data = json.loads(raw)
        ts = data.get("last_scan")
    except Exception:
        return None
    if not ts:
        return None
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def write_last_scan(scope: str, dt: datetime) -> None:
    """Persist the UTC datetime of the most recent scan to the sidecar file."""
    registry.BACKEND.put_json(_last_scan_key(scope), json.dumps({"last_scan": dt.isoformat()}))


def cloudwatch_url(log_stream: str | None) -> str | None:
    """Build a CloudWatch console deep link to a log stream, or None.

    Links to the ``/codeocean/pipelines`` log group's stream that emitted the
    event, so the full surrounding logs (and traceback) can be inspected in the
    console. The log-group and stream path segments are URL-encoded twice, as the
    CloudWatch console hash router requires.
    """
    if not log_stream:
        return None
    group = urllib.parse.quote(urllib.parse.quote(LOG_GROUP, safe=""), safe="")
    stream = urllib.parse.quote(urllib.parse.quote(log_stream, safe=""), safe="")
    return (
        f"https://{REGION}.console.aws.amazon.com/cloudwatch/home?region={REGION}"
        f"#logsV2:log-groups/log-group/{group}/log-events/{stream}"
    )


def log(table_key: str, message: str) -> None:
    """Emit a structured cache log message for an operations table."""
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES[table_key],
            message=message,
        ).to_json()
    )


def log_system(message: str) -> None:
    """Emit a structured cache log message for the combined operations pull."""
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table="operations",
            message=message,
        ).to_json()
    )


def logs_client():
    """Return a boto3 CloudWatch Logs client."""
    return boto3.client("logs")


def query_string(pipeline_name: str | None = None, acquisition_name: str | None = None) -> str:
    """Build the Logs Insights query string for pipeline lifecycle events.

    Each pipeline gets its own clause built from its log schema (event types,
    non-empty asset field, legacy-name exclusions); the clauses are OR'd together.
    When ``pipeline_name`` is None, every registered operations pipeline is matched
    (the single combined pull); otherwise only that pipeline. When
    ``acquisition_name`` is given, only that asset's events are returned.
    """
    pipelines = list(_OPERATIONS_PIPELINES) if pipeline_name is None else [pipeline_name]
    clauses = " or ".join(_pipeline_clause(p, acquisition_name) for p in pipelines)
    return "\n".join(
        [
            "fields @timestamp, @message, @logStream",
            f"| filter {clauses}",
            "| sort @timestamp asc",
        ]
    )


def _pipeline_clause(pipeline_name: str, acquisition_name: str | None) -> str:
    """Return the parenthesized Logs Insights filter for one pipeline."""
    schema = schema_for(pipeline_name)
    event_list = ", ".join(f'"{e}"' for e in schema.event_types)
    parts = [
        f'pipeline_name = "{pipeline_name}"',
        f"event_type in [{event_list}]",
        f'{schema.asset_field} != ""',
    ]
    parts.extend(f"{schema.asset_field} not like /{pattern}/" for pattern in schema.exclude_asset_patterns)
    if acquisition_name is not None:
        parts.append(f'{schema.asset_field} = "{acquisition_name}"')
    return "(" + " and ".join(parts) + ")"


def run_query(client, start_ms: int, end_ms: int, query: str) -> list[list[dict]]:
    """Run one Logs Insights query and return its raw result rows.

    Blocks until the query completes (or times out). Each row is the list of
    ``{"field": ..., "value": ...}`` dicts returned by the API.
    """
    query_id = client.start_query(
        logGroupName=LOG_GROUP,
        startTime=start_ms // 1000,
        endTime=end_ms // 1000,
        queryString=query,
        limit=MAX_QUERY_RESULTS,
    )["queryId"]
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    while True:
        resp = client.get_query_results(queryId=query_id)
        if resp["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            if resp["status"] != "Complete":
                raise RuntimeError(f"CloudWatch query {query_id} ended with status {resp['status']}")
            return resp["results"]
        if time.monotonic() > deadline:
            raise TimeoutError(f"CloudWatch query {query_id} did not complete within {QUERY_TIMEOUT_SECONDS}s")
        time.sleep(QUERY_POLL_SECONDS)


def collect_results(client, start_ms: int, end_ms: int, query: str) -> list[list[dict]]:
    """Return all result rows for a window, splitting it if the row cap is hit.

    Logs Insights caps results at ``MAX_QUERY_RESULTS``; when a window returns that
    many rows it is bisected in time and each half re-queried, recursively, so
    every event is retrieved.
    """
    results = run_query(client, start_ms, end_ms, query)
    if len(results) < MAX_QUERY_RESULTS or end_ms - start_ms <= 1000:
        return results
    mid = start_ms + (end_ms - start_ms) // 2
    return collect_results(client, start_ms, mid, query) + collect_results(client, mid, end_ms, query)


def parse_row(row: list[dict]) -> dict | None:
    """Parse one Insights result row into a normalized event dict, or None.

    ``@message`` is a JSON log record; ``@timestamp`` is CloudWatch's ingestion
    time (kept separately as ``ingest_ts``). The asset-name and error fields are
    read according to the record's pipeline log schema. Rows whose message is not
    JSON, or that lack an asset name, are skipped.
    """
    fields = {f["field"]: f["value"] for f in row}
    message = fields.get("@message")
    if not message:
        return None
    try:
        record = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return None
    schema = schema_for(record.get("pipeline_name"))
    asset_name = record.get(schema.asset_field)
    if not asset_name:
        return None
    return {
        "asset_name": asset_name,
        "pipeline_name": record.get("pipeline_name"),
        "timestamp": record.get("timestamp"),
        "ingest_ts": fields.get("@timestamp"),
        "process_name": record.get("process_name"),
        "event_type": schema.normalize_event_type(record.get("event_type")),
        "level": record.get("level"),
        "message": record.get("message"),
        "error_info": record.get(schema.error_field),
        "cloudwatch_url": cloudwatch_url(fields.get("@logStream")),
    }


def events_dataframe(rows: list[list[dict]]) -> pd.DataFrame:
    """Build a normalized events DataFrame from raw Insights result rows."""
    records = [r for r in (parse_row(row) for row in rows) if r is not None]
    df = pd.DataFrame(records, columns=EVENT_COLUMNS)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True, errors="coerce")
    df["ingest_ts"] = pd.to_datetime(df["ingest_ts"], utc=True, errors="coerce")
    return df


def window_ms(lookback_days: int) -> tuple[int, int]:
    """Return the ``(start_ms, end_ms)`` epoch-millisecond query window."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - lookback_days * 86_400_000
    return start_ms, end_ms


def write_partition(
    table_key: str,
    asset_name: str,
    df: pd.DataFrame,
    append: bool = False,
    chunk_idx: int = 0,
) -> None:
    """Sort one acquisition's events by time and write its partition.

    On an incremental run (``append=True``) the events are added as a new numbered
    chunk so previously cached events from earlier windows are preserved; the
    lookback no longer reaches those older logs. On a full rebuild the partition is
    overwritten in place.
    """
    cache_key = f"{registry.NAMES[table_key]}/{asset_name}"
    drop_cols = [c for c in ("asset_name", "pipeline_name") if c in df.columns]
    ordered = df.drop(columns=drop_cols).sort_values("timestamp").reset_index(drop=True)
    if append:
        registry.BACKEND.write_chunk(cache_key, ordered, chunk_idx)
    else:
        registry.BACKEND.clear_partition(cache_key)
        registry.BACKEND.write(cache_key, ordered)


def fetch_asset_operations(
    table_key: str,
    pipeline_name: str,
    asset_name: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Fetch and cache the processing events for a single acquisition.

    Queries CloudWatch for only this acquisition's lifecycle events. Returns an
    empty DataFrame; callers should read back from the backend.
    """
    setup_logging()
    log(table_key, f"Updating cache for asset {asset_name}")
    client = logs_client()
    start_ms, end_ms = window_ms(lookback_days)
    rows = collect_results(client, start_ms, end_ms, query_string(pipeline_name, asset_name))
    df = events_dataframe(rows)
    if df.empty:
        log(table_key, f"No processing events found for asset {asset_name}")
        return pd.DataFrame()
    write_partition(table_key, asset_name, df)
    log(table_key, f"Cached {len(df)} processing events for asset {asset_name}")
    return pd.DataFrame()


def _scan_events(scope: str, query: str, lookback_days: int):
    """Run an incremental Logs Insights pull for a scan scope.

    Returns ``(df, incremental, chunk_idx, last_scan, end_dt)``. The first run (no
    sidecar) scans the whole ``lookback_days`` window; every subsequent run reads
    the scope's ``last_scan`` sidecar and queries only events ingested after it, so
    contiguous windows neither miss nor duplicate events.
    """
    setup_logging()
    client = logs_client()
    end_dt = datetime.now(timezone.utc)
    end_ms = int(end_dt.timestamp() * 1000)
    last_scan = read_last_scan(scope)
    incremental = last_scan is not None
    if incremental:
        start_ms = int(last_scan.timestamp() * 1000)
        log_system(f"Querying {scope} events ingested since {last_scan.isoformat()}")
    else:
        start_ms = end_ms - lookback_days * 86_400_000
        log_system(f"Querying {scope} events over the last {lookback_days} days (initial scan)")
    rows = collect_results(client, start_ms, end_ms, query)
    df = events_dataframe(rows)
    if incremental and not df.empty:
        df = df[df["ingest_ts"] > last_scan]
    return df, incremental, end_ms // 1000, last_scan, end_dt


def _advance_scan(scope: str, df: pd.DataFrame, incremental: bool, last_scan, end_dt) -> None:
    """Persist the sidecar to the newest ingestion time observed this run."""
    if not df.empty:
        new_last_scan = df["ingest_ts"].max().to_pydatetime()
    elif incremental:
        new_last_scan = last_scan
    else:
        new_last_scan = end_dt
    write_last_scan(scope, new_last_scan)


def _write_events(
    df: pd.DataFrame,
    pipelines: dict[str, str],
    incremental: bool,
    chunk_idx: int,
) -> dict[str, list[str]]:
    """Route events to their tables and write one partition per acquisition.

    On an incremental run the events are appended as a new chunk; on a full run each
    partition is overwritten. Returns a mapping of table key -> acquisition names.
    """
    written: dict[str, list[str]] = {}
    for pipeline_name, table_key in pipelines.items():
        sub = df[df["pipeline_name"] == pipeline_name] if not df.empty else df
        names: list[str] = []
        for asset_name, group in sub.groupby("asset_name", sort=False):
            write_partition(table_key, asset_name, group, append=incremental, chunk_idx=chunk_idx)
            names.append(asset_name)
        if names:
            log(table_key, f"Cached processing events for {len(names)} acquisitions ({len(sub)} events)")
        else:
            log(table_key, "No new processing events found")
        written[table_key] = names
    return written


def fetch_all_operations(
    table_key: str,
    pipeline_name: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[str]:
    """Incrementally fetch a single pipeline's events and append/write partitions.

    The first run scans the whole ``lookback_days`` window; subsequent runs query
    only events ingested since this table's last scan and append them as new chunks.
    Returns the list of acquisition names written this run.
    """
    scope = registry.NAMES[table_key]
    df, incremental, chunk_idx, last_scan, end_dt = _scan_events(scope, query_string(pipeline_name), lookback_days)
    written = _write_events(df, {pipeline_name: table_key}, incremental, chunk_idx)
    _advance_scan(scope, df, incremental, last_scan, end_dt)
    return written[table_key]


def build_all_operations(lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> dict[str, list[str]]:
    """Pull CloudWatch once and build every registered operations table.

    Performs a single incremental combined pull across all registered pipelines and
    routes the events to each ``platform_*_operations`` table, so the log pull is
    done once and reused across all tables. Uses a shared ``operations`` scan sidecar
    so each run only queries newly ingested events. Returns a mapping of table key ->
    acquisition names written.
    """
    scope = "operations"
    df, incremental, chunk_idx, last_scan, end_dt = _scan_events(scope, query_string(), lookback_days)
    written = _write_events(df, dict(_OPERATIONS_PIPELINES), incremental, chunk_idx)
    _advance_scan(scope, df, incremental, last_scan, end_dt)
    if df.empty:
        log_system("No new processing events found")
    return written


def platform_operations(
    table_key: str,
    pipeline_name: str,
    asset_name: str | None,
    force_update: bool,
    lazy: bool,
) -> pd.DataFrame | str:
    """Return an operations table's events, or rebuild the whole table.

    Shared implementation of the registered ``platform_*_operations`` functions;
    see those wrappers for the full argument semantics.
    """
    if asset_name is None:
        if not force_update:
            raise ValueError(
                f"asset_name is required to read {registry.NAMES[table_key]}. Call with "
                "force_update=True (no asset_name) to rebuild the whole table."
            )
        fetch_all_operations(table_key, pipeline_name)
        return pd.DataFrame()

    cache_key = f"{registry.NAMES[table_key]}/{asset_name}"

    if lazy:
        if force_update:
            fetch_asset_operations(table_key, pipeline_name, asset_name)
        return registry.BACKEND.get_location(cache_key)

    if force_update:
        return fetch_asset_operations(table_key, pipeline_name, asset_name)

    df = registry.BACKEND.read(cache_key)
    if df.empty:
        raise ValueError(f"Cache is empty for asset {asset_name}. Use force_update=True to fetch data from CloudWatch.")
    return df


def operations_columns() -> list[Column]:
    """Return the shared column definitions for an operations cache table."""
    return [
        Column(name="timestamp", description="Event time (UTC) from the pipeline log record"),
        Column(name="ingest_ts", description="CloudWatch log ingestion time (UTC), kept separately from event time"),
        Column(name="process_name", description="Pipeline stage that emitted the event (e.g. aind-fip-dff)"),
        Column(
            name="event_type",
            description="Lifecycle event (e.g. stage_start, stage_complete, stage_error/stage_failure)",
        ),
        Column(name="level", description="Log level of the record (e.g. INFO, ERROR)"),
        Column(name="message", description="Human-readable log message"),
        Column(name="error_info", description="Error message or traceback for failure events; null otherwise"),
        Column(name="cloudwatch_url", description="Deep link to the CloudWatch console log stream for this event"),
    ]
