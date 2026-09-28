"""Quality-control metrics flattened by raw-asset lineage."""

import gc
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
QC_TAG_STATUS_BUFFER_SIZE = 5000
QC_FILTER = {"quality_control": {"$exists": True}}
QC_IDENTITY_PROJECTION = {"_id": 1, "name": 1}
QC_METADATA_PROJECTION = {
    **QC_IDENTITY_PROJECTION,
    "location": 1,
    "_created": 1,
    "acquisition.acquisition_start_time": 1,
    "subject.subject_id": 1,
    "data_description.modalities": 1,
    "data_description.data_level": 1,
    "data_description.source_data": 1,
}
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


def _processing_times_by_asset(source_df: pd.DataFrame) -> dict[str, str]:
    processing_times = {}
    if (
        source_df is None
        or source_df.empty
        or "name" not in source_df.columns
        or "processing_time" not in source_df.columns
    ):
        return processing_times

    for asset_name, processing_time in source_df[["name", "processing_time"]].itertuples(index=False, name=None):
        if not asset_name or processing_time is None or pd.isna(processing_time) or processing_time == "":
            continue
        value = str(processing_time)
        if value > processing_times.get(asset_name, ""):
            processing_times[asset_name] = value
    return processing_times


def _asset_time(asset_name: str, metadata: dict, processing_times: dict[str, str]) -> str:
    """Return the best comparable timestamp for selecting a latest chain."""
    if asset_name in processing_times:
        return processing_times[asset_name]
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
    names: set[str] = set()
    for record in records:
        name = record.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    if basics_df is not None and "name" in basics_df.columns:
        names.update(name for name in basics_df["name"].dropna().tolist() if isinstance(name, str) and name)
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
    processing_times: dict[str, str],
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
                key=lambda name: (_asset_time(name, metadata.get(name, {}), processing_times), name),
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


def _cache_tag_statuses(
    records: list[dict],
    default_subject_id: str | None = None,
    buffered_rows: dict[str, list[dict]] | None = None,
) -> int:
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
                {
                    "tag": tag,
                    "status": status,
                    "asset_name": record.get("name", ""),
                    "subject_id": subject_id,
                    "timestamp": timestamp,
                }
            )
    row_count = 0
    for subject_id, rows in by_subject.items():
        row_count += len(rows)
        if buffered_rows is not None:
            buffered_rows.setdefault(subject_id, []).extend(rows)
        else:
            tag_df = pd.DataFrame.from_records(rows)
            tag_df["timestamp"] = pd.to_datetime(tag_df["timestamp"], utc=True)
            registry.BACKEND.write(f"qc_tag_status/{subject_id}", tag_df)
    return row_count


def _flush_tag_statuses(
    buffered_rows: dict[str, list[dict]],
    chunk_indices: dict[str, int],
    cleared_subjects: set[str],
) -> None:
    """Write buffered status rows without retaining the complete status table."""
    for subject_id, rows in buffered_rows.items():
        tag_df = pd.DataFrame.from_records(rows)
        tag_df["timestamp"] = pd.to_datetime(tag_df["timestamp"], utc=True)
        cache_key = f"qc_tag_status/{subject_id}"
        if subject_id not in cleared_subjects:
            registry.BACKEND.clear_partition(cache_key)
            cleared_subjects.add(subject_id)
        chunk_idx = chunk_indices.get(subject_id, 0)
        registry.BACKEND.write_chunk(cache_key, tag_df, chunk_idx)
        chunk_indices[subject_id] = chunk_idx + 1
        del tag_df
    buffered_rows.clear()


def _build_qc_rows_for_root(
    root: str,
    records: list[dict],
    metadata: dict[str, dict],
    parents: dict[str, list[str]],
    children: dict[str, list[str]],
    processing_times: dict[str, str],
) -> list[dict]:
    records_by_name = {record.get("name"): record for record in records if record.get("name")}
    selected_nodes, distances = _select_terminal_chains(root, parents, children, metadata, processing_times)
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

    result = []
    for candidates in occurrences.values():
        origin = min(
            candidates,
            key=lambda item: (
                item[0],
                _asset_time(item[1], metadata.get(item[1], {}), processing_times),
                item[1],
                item[2],
            ),
        )
        origin_distance, asset_name, metric_index, metric, record = origin
        downstream = sorted(
            {
                candidate[1]
                for candidate in candidates
                if candidate[1] != asset_name and candidate[0] >= origin_distance
            },
            key=lambda name: (
                distances.get(name, 0),
                _asset_time(name, metadata.get(name, {}), processing_times),
                name,
            ),
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


def build_qc_rows(records: list[dict], basics_df: pd.DataFrame, source_df: pd.DataFrame) -> list[dict]:
    """Build de-duplicated QC rows for all raw roots in a metadata snapshot.

    The selected terminal is the newest asset for each distinct terminal modality
    set. Every selected chain contributes metrics, but an inherited metric is
    represented by its earliest occurrence and carries the later asset names.
    """
    metadata = _metadata_by_asset(basics_df)
    parents = _source_mapping(source_df)
    children = _children_mapping(parents)
    processing_times = _processing_times_by_asset(source_df)
    names = _all_assets(records, basics_df, parents)

    roots = []
    seen_roots = set()
    for name in sorted(names):
        root = _raw_roots(name, parents)[0]
        if root not in seen_roots:
            roots.append(root)
            seen_roots.add(root)

    result = []
    for root in roots:
        result.extend(_build_qc_rows_for_root(root, records, metadata, parents, children, processing_times))
    return result


def _cached_lineage_inputs(records: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    basics_result = registry.BACKEND.read_filtered(
        registry.NAMES["basics"],
        columns=[
            "name",
            "location",
            "data_level",
            "modalities",
            "subject_id",
            "created",
            "process_date",
            "acquisition_start_time",
        ],
        limit=None,
    )
    basics_df = basics_result[0] if isinstance(basics_result, tuple) else basics_result
    if basics_df.empty:
        basics_df = _record_basics(records)

    source_result = registry.BACKEND.read_filtered(
        registry.NAMES["d2r"],
        columns=["name", "source_data", "processing_time"],
        limit=None,
    )
    source_df = source_result[0] if isinstance(source_result, tuple) else source_result
    if source_df.empty:
        source_df = _record_sources(records)
    return basics_df, source_df


def _qc_roots_and_record_ids(
    index_records: list[dict], basics_df: pd.DataFrame, parents: dict[str, list[str]]
) -> tuple[list[str], dict[str, list[object]], list[object]]:
    names = _all_assets(index_records, basics_df, parents)
    roots = []
    seen_roots = set()
    for name in sorted(names):
        root = _raw_roots(name, parents)[0]
        if root not in seen_roots:
            roots.append(root)
            seen_roots.add(root)

    record_ids_by_root: dict[str, list[object]] = defaultdict(list)
    orphan_record_ids = []
    seen_record_ids = set()
    for record in index_records:
        record_id = record.get("_id")
        if not record_id or record_id in seen_record_ids:
            continue
        seen_record_ids.add(record_id)
        name = record.get("name")
        if not name:
            orphan_record_ids.append(record_id)
            continue
        record_roots = _raw_roots(name, parents)
        if not record_roots:
            orphan_record_ids.append(record_id)
            continue
        for root in record_roots:
            if root not in seen_roots:
                roots.append(root)
                seen_roots.add(root)
            record_ids_by_root[root].append(record_id)
    return roots, record_ids_by_root, orphan_record_ids


def _qc_root_groups(roots: list[str], record_ids_by_root: dict[str, list[object]]):
    grouped_roots = []
    grouped_ids = []
    grouped_id_set = set()
    for root in roots:
        root_record_ids = record_ids_by_root.pop(root, [])
        if not root_record_ids:
            continue
        new_ids = [record_id for record_id in root_record_ids if record_id not in grouped_id_set]
        if grouped_roots and len(grouped_ids) + len(new_ids) > QC_FETCH_BATCH_SIZE:
            yield grouped_roots, grouped_ids
            grouped_roots = []
            grouped_ids = []
            grouped_id_set = set()
            new_ids = list(dict.fromkeys(root_record_ids))
        grouped_roots.append((root, root_record_ids))
        for record_id in new_ids:
            grouped_ids.append(record_id)
            grouped_id_set.add(record_id)
        if len(grouped_ids) >= QC_FETCH_BATCH_SIZE:
            yield grouped_roots, grouped_ids
            grouped_roots = []
            grouped_ids = []
            grouped_id_set = set()
    if grouped_roots:
        yield grouped_roots, grouped_ids


def _fetch_qc_record_index(client, projection: dict) -> list[dict]:
    """Fetch the lightweight QC record index used to group work by raw root."""
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["qc"],
            message="Fetching QC record index",
        ).to_json()
    )
    return client.retrieve_docdb_records(
        filter_query=QC_FILTER,
        projection=projection,
        limit=0,
    )


def _fetch_qc_records(client, record_ids: list[object], on_batch=None, collect_records: bool = True) -> list[dict]:
    """Fetch one raw root's QC records in bounded batches."""
    records = [] if collect_records else None
    total = len(record_ids)
    fetched = 0
    for start in range(0, total, QC_FETCH_BATCH_SIZE):
        batch_ids = record_ids[start : start + QC_FETCH_BATCH_SIZE]
        batch_records = client.retrieve_docdb_records(
            filter_query={"_id": {"$in": batch_ids}},
            projection=QC_PROJECTION,
            limit=len(batch_ids),
        )
        if on_batch is not None:
            on_batch(batch_records)
        if records is not None:
            records.extend(batch_records)
        fetched += len(batch_records)
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc"],
                message=f"Fetched {fetched}/{total} QC records for one raw root",
            ).to_json()
        )
        del batch_records
    return records if records is not None else []


def _fetch_all_qc(return_df: bool = True) -> pd.DataFrame:
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
    index_records = _fetch_qc_record_index(client, QC_METADATA_PROJECTION)
    if not index_records:
        logging.warning(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc"],
                message="No quality_control records found",
            ).to_json()
        )
        return pd.DataFrame()

    basics_df, source_df = _cached_lineage_inputs(index_records)
    metadata = _metadata_by_asset(basics_df)
    parents = _source_mapping(source_df)
    children = _children_mapping(parents)
    processing_times = _processing_times_by_asset(source_df)
    roots, record_ids_by_root, orphan_record_ids = _qc_roots_and_record_ids(index_records, basics_df, parents)
    del basics_df, source_df, index_records

    result_rows = [] if return_df else None
    total_rows = 0
    buffered_tag_rows: dict[str, list[dict]] = defaultdict(list)
    tag_chunk_indices: dict[str, int] = {}
    cleared_tag_subjects: set[str] = set()
    tag_status_record_ids: set[object] = set()
    buffered_tag_row_count = 0

    def cache_tag_batch(batch_records: list[dict]) -> None:
        nonlocal buffered_tag_row_count
        unique_records = []
        for record in batch_records:
            record_id = record.get("_id")
            if record_id is not None:
                if record_id in tag_status_record_ids:
                    continue
                tag_status_record_ids.add(record_id)
            unique_records.append(record)
        buffered_tag_row_count += _cache_tag_statuses(unique_records, buffered_rows=buffered_tag_rows)
        if buffered_tag_row_count >= QC_TAG_STATUS_BUFFER_SIZE:
            _flush_tag_statuses(buffered_tag_rows, tag_chunk_indices, cleared_tag_subjects)
            buffered_tag_row_count = 0
        del unique_records

    for root_group, group_ids in _qc_root_groups(roots, record_ids_by_root):
        fetched_records = _fetch_qc_records(client, group_ids, on_batch=cache_tag_batch)
        records_by_id = {record.get("_id"): record for record in fetched_records if record.get("_id") is not None}
        del fetched_records

        remaining_uses: dict[object, int] = defaultdict(int)
        for _, root_record_ids in root_group:
            for record_id in dict.fromkeys(root_record_ids):
                remaining_uses[record_id] += 1

        for root, root_record_ids in root_group:
            root_records = [
                records_by_id[record_id]
                for record_id in dict.fromkeys(root_record_ids)
                if record_id in records_by_id
            ]
            rows = _build_qc_rows_for_root(root, root_records, metadata, parents, children, processing_times)
            cache_key = f"{QC_STORAGE_NAME}/{root}"
            root_df = None
            if rows:
                root_df = pd.DataFrame.from_records(rows)
                root_df["timestamp"] = pd.to_datetime(root_df["timestamp"], utc=True)
                registry.BACKEND.clear_partition(cache_key)
                registry.BACKEND.write(cache_key, root_df)
                total_rows += len(rows)
                if result_rows is not None:
                    result_rows.extend(rows)
            else:
                registry.BACKEND.clear_partition(cache_key)

            for record_id in dict.fromkeys(root_record_ids):
                remaining_uses[record_id] -= 1
                if remaining_uses[record_id] == 0:
                    records_by_id.pop(record_id, None)
            del root_records, rows, root_df

        del records_by_id, remaining_uses, root_group, group_ids
        gc.collect()

    for start in range(0, len(orphan_record_ids), QC_FETCH_BATCH_SIZE):
        orphan_batch = orphan_record_ids[start : start + QC_FETCH_BATCH_SIZE]
        _fetch_qc_records(client, orphan_batch, on_batch=cache_tag_batch, collect_records=False)
        del orphan_batch

    if buffered_tag_rows:
        _flush_tag_statuses(buffered_tag_rows, tag_chunk_indices, cleared_tag_subjects)

    del record_ids_by_root, orphan_record_ids, roots, metadata, parents, children, processing_times
    del tag_status_record_ids, tag_chunk_indices, cleared_tag_subjects, buffered_tag_rows
    gc.collect()

    if total_rows == 0:
        logging.warning(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=registry.NAMES["qc"],
                message="No quality_control metrics found",
            ).to_json()
        )

    if result_rows is None or not result_rows:
        return pd.DataFrame()
    df = pd.DataFrame.from_records(result_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    del result_rows
    gc.collect()
    return df


@registry.register_table(registry.NAMES["qc"])
def qc(
    raw_asset_name: str | None = None,
    asset_names: str | list[str] | None = None,
    force_update: bool = False,
    lazy: bool = False,
    return_df: bool = True,
) -> pd.DataFrame | str:
    """Read a raw-asset QC partition, rebuilding all partitions when requested.

    ``asset_names`` optionally narrows a raw partition to the metric origin
    assets. The published table is partitioned by ``raw_asset_name``.
    """
    if raw_asset_name is None:
        df = _fetch_all_qc(return_df=return_df) if force_update else pd.DataFrame()
        return df

    cache_key = f"{QC_STORAGE_NAME}/{raw_asset_name}"
    if force_update:
        _fetch_all_qc(return_df=False)
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
