"""Metadata core files presence cache table."""

import logging

import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import (
    CacheLogMessage,
    setup_logging,
)

CORE_FILES = [
    "subject",
    "data_description",
    "procedures",
    "instrument",
    "acquisition",
    "processing",
    "quality_control",
]


@registry.register_table(registry.NAMES["core"])
def metadata_core(force_update: bool = False) -> pd.DataFrame:
    """Fetch presence of core aind-data-schema metadata files for each asset.

    Returns a DataFrame with a boolean column per core file indicating whether
    that file is present (not null) in the asset's DocDB record. Uses
    incremental updates based on _last_modified timestamps.

    Args:
        force_update: If True, bypass cache and fetch fresh data from database.

    Returns:
        DataFrame with _id and one boolean column per core metadata file.

    """
    df = registry.BACKEND.read(registry.NAMES["core"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if not df.empty or force_update:
        setup_logging()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__, table=registry.NAMES["core"], message="Updating cache"
            ).to_json()
        )
        columns = ["_id", "_last_modified"] + CORE_FILES

        from aind_data_access_api.document_db import MetadataDbClient

        client = MetadataDbClient(
            host=registry.API_GATEWAY_HOST,
            version="v2",
        )

        if df.empty:
            df = pd.DataFrame(columns=columns)

        record_ids = client.retrieve_docdb_records(
            filter_query={},
            projection={"_id": 1, "_last_modified": 1},
            limit=0,
        )

        cached_last_modified = dict(zip(df["_id"], df["_last_modified"], strict=False))
        current_ids = {record["_id"] for record in record_ids}
        update_ids = [
            record["_id"]
            for record in record_ids
            if force_update or cached_last_modified.get(record["_id"]) != record["_last_modified"]
        ]
        del record_ids

        BATCH_SIZE = 25
        rows = []
        for i in range(0, len(update_ids), BATCH_SIZE):
            logging.info(
                CacheLogMessage(
                    backend=registry.BACKEND.__class__.__name__,
                    table=registry.NAMES["core"],
                    message=f"Fetching batch {i // BATCH_SIZE + 1}",
                ).to_json()
            )
            batch_ids = update_ids[i : i + BATCH_SIZE]
            batch_records = client.retrieve_docdb_records(
                filter_query={"_id": {"$in": batch_ids}},
                projection={"_id": 1, "_last_modified": 1, **{f: 1 for f in CORE_FILES}},
                limit=0,
            )
            rows.extend(
                [
                    {
                        "_id": record["_id"],
                        "_last_modified": record.get("_last_modified"),
                        **{core_file: record.get(core_file) is not None for core_file in CORE_FILES},
                    }
                    for record in batch_records
                ]
            )
            del batch_records

        new_df = pd.DataFrame(rows, columns=columns)
        if force_update:
            df = new_df
        else:
            cached_rows = df[df["_id"].isin(current_ids) & ~df["_id"].isin(update_ids)]
            df = pd.concat([cached_rows, new_df], ignore_index=True)

        registry.BACKEND.write(registry.NAMES["core"], df)

    return df


def metadata_core_columns() -> list[Column]:
    """Return metadata core cache table column definitions."""
    return [
        Column(name="_id", description="DocDB record ID for the asset"),
        Column(name="_last_modified", description="DocDB last modified timestamp for the asset record"),
        Column(name="subject", description="Whether subject.json is present (not null)"),
        Column(name="data_description", description="Whether data_description.json is present (not null)"),
        Column(name="procedures", description="Whether procedures.json is present (not null)"),
        Column(name="instrument", description="Whether instrument.json is present (not null)"),
        Column(name="acquisition", description="Whether acquisition.json is present (not null)"),
        Column(name="processing", description="Whether processing.json is present (not null)"),
        Column(name="quality_control", description="Whether quality_control.json is present (not null)"),
    ]
