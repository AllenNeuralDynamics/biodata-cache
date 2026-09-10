"""Quality-control metrics flattened by raw-asset lineage."""

import json
import logging
from collections import defaultdict, deque
from datetime import datetime

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

QC_METRIC_FIELDS = [
    "name",
    "modality",
    "stage",
    "value",
    "status_history",
    "description",
    "reference",
    "tags",
    "object_type",
    "type",
    "evaluated_assets",
]

# ``quality_control`` is the published table name, while ``qc`` is its
# historical storage name and the key understood by the backends.
QC_STORAGE_NAME = "qc"
QC_FETCH_BATCH_SIZE = 50
QC_FILTER = {"quality_control": {"$exists": True}}
QC_PROJECTION = {
    "_id": 1,
    "name": 1,
    "location": 1,
    "_created": 1,
    "quality_control.metrics": 1,
    "quality_control.default_grouping": 1,
    "quality_control.status": 1,
    "acquisition.acquisition_start_time": 1,
    "subject.subject_id": 1,
    "data_description.modalities": 1,
    "data_description.data_level": 1,
    "data_description.source_data": 1,
}


def _json_default(value):
    """Make uncommon DocDB scalar values safe to serialize into Parquet."""
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    return str(value)


def _json_dumps(value) -> str:
    return json.dumps(value, sort_keys=True, default=_json_default)


def _metric_modality(metric: dict) -> str | None:
    modality = metric.get("modality")
    if isinstance(modality, dict):
        return modality.get("abbreviation")
    return modality if isinstance(modality, str) else None


def _metric_identity(metric: dict) -> str:
    """Identify an inherited metric without treating a changed status as new."""
    identity = {
        "name": metric.get("name"),
        "modality": _metric_modality(metric),
        "stage": metric.get("stage"),
        "tags": metric.get("tags"),
    }
    return _json_dumps(identity)


def _latest_status(metric: dict):
    history = metric.get("status_history") or []
    if not isinstance(history, list) or not history:
        return None
    latest = history[-1]
    return latest.get("status") if isinstance(latest, dict) else None


def _metric_value(value):
    if isinstance(value, (dict, list)):
        return _json_dumps(value)
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _json_field(value):
    if value is None:
        return None
    return _json_dumps(value)


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(value)]


def _source_mapping(source_df: pd.DataFrame) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = defaultdict(list)
    if source_df is None or source_df.empty:
        return parents
    for row in source_df.to_dict("records"):
        child = row.get("name")
        if not child:
            continue
        for parent in _as_list(row.get("source_data")):
            if parent and parent not in parents[child]:
                parents[child].append(parent)
    return parents


def _children_mapping(parents: dict[str, list[str]]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = defaultdict(list)
    for child, sources in parents.items():
        for source in sources:
            if child not in children[source]:
                children[source].append(child)
    return children


def _asset_modalities(value) -> tuple[str, ...]:
    result = []
    if not isinstance(value, (list, tuple, set)):
        return ()
    for item in value:
        if isinstance(item, dict):
            item = item.get("abbreviation")
        if item:
            result.append(str(item))
    return tuple(sorted(set(result), key=str.casefold))


def _metadata_by_asset(basics_df: pd.DataFrame) -> dict[str, dict]:
    if basics_df is None or basics_df.empty or "name" not in basics_df.columns:
        return {}
    return {row["name"]: row for row in basics_df.to_dict("records") if row.get("name")}


def _asset_time(asset_name: str, metadata: dict, source_df: pd.DataFrame) -> str:
    """Return the best comparable timestamp for selecting a latest chain."""
    if (
        source_df is not None
        and not source_df.empty
        and "name" in source_df.columns
        and "processing_time" in source_df.columns
    ):
        values = source_df.loc[source_df["name"] == asset_name, "processing_time"]
        values = [
            str(value)
            for value in values.tolist()
            if value is not None and not pd.isna(value) and value != ""
        ]
        if values:
            return max(values)
    for field in ("created", "process_date", "acquisition_start_time"):
        value = metadata.get(field)
        if value is not None and not pd.isna(value):
            return str(value)
    return ""


def _record_basics(records: list[dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        dd = record.get("data_description", {}) or {}
        rows.append(
            {
                "name": record.get("name"),
                "location": record.get("location"),
                "data_level": dd.get("data_level"),
                "modalities": [
                    item.get("abbreviation")
                    for item in (dd.get("modalities") or [])
                    if isinstance(item, dict) and item.get("abbreviation")
                ],
                "subject_id": (record.get("subject", {}) or {}).get("subject_id"),
                "acquisition_start_time": (record.get("acquisition", {}) or {}).get("acquisition_start_time"),
                "created": record.get("_created"),
            }
        )
    return pd.DataFrame(rows)


def _record_sources(records: list[dict]) -> pd.DataFrame:
    rows = []
    for record in records:
        name = record.get("name")
        dd = record.get("data_description", {}) or {}
        for source in _as_list(dd.get("source_data")):
            rows.append({"name": name, "source_data": source, "processing_time": "", "pipeline_name": ""})
    return pd.DataFrame(rows, columns=["name", "source_data", "pipeline_name", "processing_time"])


def _all_assets(records: list[dict], basics_df: pd.DataFrame, parents: dict[str, list[str]]) -> set[str]:
    names = {record.get("name") for record in records if record.get("name")}
    if basics_df is not None and "name" in basics_df.columns:
        names.update(name for name in basics_df["name"].dropna().tolist())
    names.update(parents)
    for sources in parents.values():
        names.update(sources)
    return names


def _raw_roots(asset_name: str, parents: dict[str, list[str]], seen: set[str] | None = None) -> list[str]:
    """Return raw roots, preserving source_data order and breaking cycles safely."""
    seen = set() if seen is None else seen
    if asset_name in seen:
        return [asset_name]
    sources = parents.get(asset_name, [])
    if not sources:
        return [asset_name]
    roots = []
    for source in sources:
        for root in _raw_roots(source, parents, seen | {asset_name}):
            if root not in roots:
                roots.append(root)
    return roots or [asset_name]


def _descendants(root: str, children: dict[str, list[str]]) -> set[str]:
    result = {root}
    queue = deque([root])
    while queue:
        current = queue.popleft()
        for child in children.get(current, []):
            if child not in result:
                result.add(child)
                queue.append(child)
    return result


def _chain_distance(root: str, nodes: set[str], children: dict[str, list[str]]) -> dict[str, int]:
    distances = {root: 0}
    queue = deque([root])
    while queue:
        current = queue.popleft()
        for child in children.get(current, []):
            if child in nodes and child not in distances:
                distances[child] = distances[current] + 1
                queue.append(child)
    return distances


def _select_terminal_chains(
    root: str,
    parents: dict[str, list[str]],
    children: dict[str, list[str]],
    metadata: dict,
    source_df: pd.DataFrame,
) -> tuple[set[str], dict[str, int]]:
    nodes = _descendants(root, children)
    leaves = [node for node in nodes if not any(child in nodes for child in children.get(node, []))]
    if not leaves:
        leaves = [root]
    by_modalities: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for leaf in leaves:
        by_modalities[_asset_modalities(metadata.get(leaf, {}).get("modalities"))].append(leaf)

    selected_leaves = []
    for candidates in by_modalities.values():
        selected_leaves.append(
            max(
                candidates,
                key=lambda name: (_asset_time(name, metadata.get(name, {}), source_df), name),
            )
        )

    distances = _chain_distance(root, nodes, children)
    selected_nodes = set()
    for leaf in selected_leaves:
        selected_nodes.add(leaf)
        queue = deque([leaf])
        while queue:
            current = queue.popleft()
            for parent in parents.get(current, []):
                if parent in nodes and parent not in selected_nodes:
                    selected_nodes.add(parent)
                    queue.append(parent)
    return selected_nodes, distances


def _row_for_metric(
    metric: dict,
    metric_index: int,
    asset_name: str,
    raw_asset_name: str,
    downstream_asset_names: list[str],
    metadata: dict,
    record: dict,
) -> dict:
    modality = _metric_modality(metric)
    acquisition = (record.get("acquisition", {}) or {}).get("acquisition_start_time")
    try:
        timestamp = datetime.fromisoformat(acquisition.replace("Z", "+00:00")) if acquisition else None
    except (AttributeError, TypeError, ValueError):
        timestamp = None
    return {
        "name": metric.get("name"),
        "stage": metric.get("stage"),
        "modality": modality,
        "value": _metric_value(metric.get("value")),
        "status": _latest_status(metric),
        "asset_name": asset_name,
        "raw_asset_name": raw_asset_name,
        "subject_id": metadata.get("subject_id") or (record.get("subject", {}) or {}).get("subject_id"),
        "timestamp": timestamp,
        "description": metric.get("description"),
        "reference": metric.get("reference"),
        "tags": _json_field(metric.get("tags")),
        "object_type": metric.get("object_type"),
        "type": metric.get("type"),
        "evaluated_assets": _json_field(metric.get("evaluated_assets")),
        "metric_index": metric_index,
        "metric_key": _metric_identity(metric),
        "metric_json": _json_dumps(metric),
        "default_grouping": _json_field((record.get("quality_control", {}) or {}).get("default_grouping")),
        "downstream_asset_names": downstream_asset_names,
        "asset_location": metadata.get("location"),
        "asset_data_level": metadata.get("data_level"),
    }


def _cache_tag_statuses(records: list[dict], default_subject_id: str | None = None) -> None:
    """Keep the legacy tag-status cache available for downstream consumers."""
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        quality_control = record.get("quality_control", {}) or {}
        statuses = quality_control.get("status", {})
        if not isinstance(statuses, dict):
            continue
        subject_id = (record.get("subject", {}) or {}).get("subject_id") or default_subject_id
        if not subject_id:
            continue
        timestamp = (record.get("acquisition", {}) or {}).get("acquisition_start_time")
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")) if timestamp else None
        except (AttributeError, TypeError, ValueError):
            timestamp = None
        for tag, status in statuses.items():
            by_subject[subject_id].append(
                {"tag": tag, "status": status, "asset_name": record.get("name", ""), "subject_id": subject_id, "timestamp": timestamp}
            )
    for subject_id, rows in by_subject.items():
        tag_df = pd.DataFrame.from_records(rows)
        tag_df["timestamp"] = pd.to_datetime(tag_df["timestamp"], utc=True)
        registry.BACKEND.write(f"qc_tag_status/{subject_id}", tag_df)


def build_qc_rows(records: list[dict], basics_df: pd.DataFrame, source_df: pd.DataFrame) -> list[dict]:
    """Build de-duplicated QC rows for all raw roots in a metadata snapshot.

    The selected terminal is the newest asset for each distinct terminal modality
    set. Every selected chain contributes metrics, but an inherited metric is
    represented by its earliest occurrence and carries the later asset names.
    """
    records_by_name = {record.get("name"): record for record in records if record.get("name")}
    metadata = _metadata_by_asset(basics_df)
    parents = _source_mapping(source_df)
    children = _children_mapping(parents)
    names = _all_assets(records, basics_df, parents)

    roots = []
    for name in sorted(names):
        root = _raw_roots(name, parents)[0]
        if root not in roots:
            roots.append(root)

    result = []
    for root in roots:
        selected_nodes, distances = _select_terminal_chains(root, parents, children, metadata, source_df)
        occurrences: dict[str, list[tuple[int, str, int, dict, dict]]] = defaultdict(list)
        for asset_name in sorted(selected_nodes):
            record = records_by_name.get(asset_name)
            if not record:
                continue
            qc_data = record.get("quality_control", {}) or {}
            for metric_index, metric in enumerate(qc_data.get("metrics", []) or []):
                if not isinstance(metric, dict) or not metric.get("name"):
                    continue
                occurrences[_metric_identity(metric)].append(
                    (distances.get(asset_name, 0), asset_name, metric_index, metric, record)
                )

        for candidates in occurrences.values():
            origin = min(
                candidates,
                key=lambda item: (item[0], _asset_time(item[1], metadata.get(item[1], {}), source_df), item[1], item[2]),
            )
            origin_distance, asset_name, metric_index, metric, record = origin
            downstream = sorted(
                {
                    candidate[1]
                    for candidate in candidates
                    if candidate[1] != asset_name and candidate[0] >= origin_distance
                },
                key=lambda name: (distances.get(name, 0), _asset_time(name, metadata.get(name, {}), source_df), name),
            )
            result.append(
                _row_for_metric(
                    metric,
                    metric_index,
                    asset_name,
                    root,
                    downstream,
                    metadata.get(asset_name, {}),
                    record,
                )
            )
    return result


def _cached_lineage_inputs(records: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    basics_df = registry.BACKEND.read(registry.NAMES["basics"])
    if basics_df.empty:
        basics_df = _record_basics(records)
    source_df = registry.BACKEND.read(registry.NAMES["d2r"])
    if source_df.empty:
        source_df = _record_sources(records)
    return basics_df, source_df


def _fetch_qc_records(client) -> list[dict]:
    """Fetch QC-bearing records in bounded batches instead of one huge response."""
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["qc"],
            message="Fetching QC record IDs",
        ).to_json()
    )
    id_records = client.retrieve_docdb_records(
        filter_query=QC_FILTER,
        projection={"_id": 1},
        limit=0,
    )
    record_ids = list(dict.fromkeys(record.get("_id") for record in id_records if record.get("_id")))
    if not record_ids:
        return []

    records = []
    total = len(record_ids)
    for start in range(0, total, QC_FETCH_BATCH_SIZE):
        batch_ids = record_ids[start : start + QC_FETCH_BATCH_SIZE]
        records.extend(
            client.retrieve_docdb_records(
                filter_query={"_id": {"$in": batch_ids}},
                projection=QC_PROJECTION,
                limit=len(batch_ids),
            )
        )
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc"],
                message=f"Fetched {len(records)}/{total} QC records",
            ).to_json()
        )
    return records


def _fetch_all_qc() -> pd.DataFrame:
    setup_logging()
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["qc"],
            message="Updating raw-asset QC partitions",
        ).to_json()
    )

    from aind_data_access_api.document_db import MetadataDbClient

    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
    records = _fetch_qc_records(client)
    if not records:
        return pd.DataFrame()

    basics_df, source_df = _cached_lineage_inputs(records)
    rows = build_qc_rows(records, basics_df, source_df)
    if not rows:
        logging.warning(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc"],
                message="No quality_control metrics found",
            ).to_json()
        )
        return pd.DataFrame()

    df = pd.DataFrame.from_records(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for raw_asset_name, partition in df.groupby("raw_asset_name", sort=False):
        registry.BACKEND.write(f"{QC_STORAGE_NAME}/{raw_asset_name}", partition.reset_index(drop=True))
    _cache_tag_statuses(records)
    return df


@registry.register_table(registry.NAMES["qc"])
def qc(
    raw_asset_name: str | None = None,
    asset_names: str | list[str] | None = None,
    force_update: bool = False,
    lazy: bool = False,
) -> pd.DataFrame | str:
    """Read a raw-asset QC partition, rebuilding all partitions when requested.

    ``asset_names`` optionally narrows a raw partition to the metric origin
    assets. The published table is partitioned by ``raw_asset_name``.
    """
    if raw_asset_name is None:
        df = _fetch_all_qc() if force_update else pd.DataFrame()
        return df

    cache_key = f"{QC_STORAGE_NAME}/{raw_asset_name}"
    if force_update:
        _fetch_all_qc()
    df = registry.BACKEND.read(cache_key)
    if asset_names is not None and not df.empty and "asset_name" in df.columns:
        names = [asset_names] if isinstance(asset_names, str) else asset_names
        df = df[df["asset_name"].isin(names)].reset_index(drop=True)
    if df.empty and not force_update:
        logging.error(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc"],
                message=f"Cache is empty for raw asset {raw_asset_name}. Use force_update=True to rebuild.",
            ).to_json()
        )
    if lazy:
        return registry.BACKEND.get_location(cache_key)
    return df


def qc_columns() -> list[Column]:
    """Return QC cache table column definitions."""
    return [
        Column(name="name", description="Metric name"),
        Column(name="stage", description="Metric stage: raw, processing, or analysis"),
        Column(name="modality", description="Modality abbreviation"),
        Column(name="value", description="Metric value; objects and arrays are JSON strings"),
        Column(name="status", description="Latest metric status (Pass, Fail, Pending)"),
        Column(name="asset_name", description="Asset where the earliest metric version was generated"),
        Column(name="raw_asset_name", description="Raw root asset for this QC chain; the partition key"),
        Column(name="subject_id", description="Subject ID"),
        Column(name="timestamp", description="Acquisition start time of the source asset"),
        Column(name="description", description="Metric description"),
        Column(name="reference", description="Metric reference media or URL"),
        Column(name="tags", description="Metric tags as a JSON string"),
        Column(name="object_type", description="QC metric object type"),
        Column(name="type", description="Optional curation metric type"),
        Column(name="evaluated_assets", description="Evaluated assets as a JSON string"),
        Column(name="metric_index", description="Metric index in the source asset QC record"),
        Column(name="metric_key", description="Stable identity used to detect inherited metric versions"),
        Column(name="metric_json", description="Complete source QC metric as JSON"),
        Column(name="default_grouping", description="Source QC default grouping as a JSON string"),
        Column(name="downstream_asset_names", description="Downstream assets carrying this metric version"),
        Column(name="asset_location", description="S3 location of the source asset"),
        Column(name="asset_data_level", description="Data level of the source asset"),
    ]
