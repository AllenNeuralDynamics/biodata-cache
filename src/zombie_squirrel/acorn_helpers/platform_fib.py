"""Platform fiber photometry acorn."""

import logging
import re

import pandas as pd
from aind_data_access_api.document_db import MetadataDbClient

import zombie_squirrel.acorns as acorns
from zombie_squirrel.acorn_helpers.asset_basics import asset_basics
from zombie_squirrel.squirrel import Column
from zombie_squirrel.utils import SquirrelMessage, setup_logging

BATCH_SIZE = 100
MAX_FIBERS = 4


def _fetch_fib_records(asset_names: list[str]) -> list[dict]:
    """Fetch fiber photometry metadata for assets from the document DB in batches of 100."""
    client = MetadataDbClient(
        host=acorns.API_GATEWAY_HOST,
        version="v2",
    )
    fields = [
        "name",
        "procedures.subject_procedures",
        "acquisition.data_streams",
    ]
    projection = {field: 1 for field in fields + ["_id"]}
    all_records = []
    for i in range(0, len(asset_names), BATCH_SIZE):
        batch = asset_names[i : i + BATCH_SIZE]
        batch_records = client.retrieve_docdb_records(
            filter_query={"name": {"$in": batch}},
            projection=projection,
            limit=0,
        )
        all_records.extend(batch_records)
    return all_records


def _extract_fiber_channel_map(record: dict) -> dict[str, str | None]:
    """Build a map of fiber name -> intended_measurement from acquisition data_streams.

    Looks through all Patch cord config entries in all data streams. The channel_name
    field encodes the fiber (e.g. 'Fiber 0_green'); we take the first channel per patch
    cord config since only one channel per fiber is supported.
    """
    fiber_channel: dict[str, str | None] = {}
    for stream in (record.get("acquisition") or {}).get("data_streams") or []:
        for config in stream.get("configurations") or []:
            if config.get("object_type") != "Patch cord config":
                continue
            channels = config.get("channels") or []
            if not channels:
                continue
            ch = channels[0]
            channel_name = ch.get("channel_name", "")
            # channel_name is like "Fiber 0_green" — derive fiber id from prefix before underscore
            parts = channel_name.split("_")
            fiber_key = parts[0] if parts else channel_name
            fiber_channel[fiber_key] = ch.get("intended_measurement")
    return fiber_channel


def _extract_fiber_structure_map(record: dict) -> dict[str, str | None]:
    """Build a map of fiber name -> targeted_structure acronym from procedures.

    Walks through subject_procedures -> surgery procedures -> Probe implant entries.
    """
    fiber_structure: dict[str, str | None] = {}
    procs_root = record.get("procedures") or {}
    for subject_proc in procs_root.get("subject_procedures") or []:
        for proc in subject_proc.get("procedures") or []:
            if proc.get("object_type") != "Probe implant":
                continue
            device = proc.get("implanted_device") or {}
            fiber_name = device.get("name")
            if not fiber_name:
                continue
            config = proc.get("device_config") or {}
            targeted = config.get("primary_targeted_structure") or {}
            fiber_structure[fiber_name] = targeted.get("acronym")
    return fiber_structure


def _fiber_sort_key(fiber_name: str) -> int:
    """Extract trailing integer from fiber name for ordering (e.g. 'Fiber_0' -> 0)."""
    match = re.search(r"(\d+)$", fiber_name)
    return int(match.group(1)) if match else 0


def _lookup_channel(fiber_name: str, fiber_channel: dict[str, str | None]) -> str | None:
    """Look up intended_measurement for a fiber, trying both underscore and space variants."""
    if fiber_name in fiber_channel:
        return fiber_channel[fiber_name]
    return fiber_channel.get(fiber_name.replace("_", " "))


def _build_fib_rows(records: list[dict]) -> list[dict]:
    """Build one row per asset with fiber_N_targeted_structure and fiber_N_intended_measurement columns."""
    rows = []
    for record in records:
        asset_name = record.get("name")
        fiber_structure = _extract_fiber_structure_map(record)
        fiber_channel = _extract_fiber_channel_map(record)

        sorted_fibers = sorted(fiber_structure.keys(), key=_fiber_sort_key)

        row: dict = {"asset_name": asset_name}
        for i in range(MAX_FIBERS):
            fiber_name = sorted_fibers[i] if i < len(sorted_fibers) else None
            row[f"fiber_{i}_targeted_structure"] = fiber_structure[fiber_name] if fiber_name else None
            row[f"fiber_{i}_intended_measurement"] = _lookup_channel(fiber_name, fiber_channel) if fiber_name else None
        rows.append(row)
    return rows


@acorns.register_acorn(acorns.NAMES["fib"])
def platform_fib(force_update: bool = False) -> pd.DataFrame:
    """Build a DataFrame of fiber photometry assets with per-fiber targeting and channel info.

    Fetches raw fiber photometry assets (modality 'fib') from asset_basics, then
    enriches with procedures and acquisition metadata. One row per asset with up to
    4 fiber columns, each containing the targeted brain structure acronym and the
    intended measurement of the channel attached to that fiber. Results are cached.

    Args:
        force_update: If True, bypass cache and rebuild from database.

    Returns:
        DataFrame with one row per asset and columns: asset_name,
        fiber_0_targeted_structure, fiber_0_intended_measurement, ...,
        fiber_3_targeted_structure, fiber_3_intended_measurement.
    """
    df = acorns.TREE.scurry(acorns.NAMES["fib"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn=acorns.NAMES["fib"],
                message="Updating cache",
            ).to_json()
        )

        basics = asset_basics()
        fib_assets = basics[basics["modalities"].str.contains("fib", case=False, na=False)]
        fib_names = list(fib_assets["name"].dropna())

        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn=acorns.NAMES["fib"],
                message=f"Fetching metadata for {len(fib_names)} fiber photometry assets",
            ).to_json()
        )

        records = _fetch_fib_records(fib_names)
        rows = _build_fib_rows(records)
        df = pd.DataFrame(rows)

        acorns.TREE.hide(acorns.NAMES["fib"], df)

    return df


def platform_fib_columns() -> list[Column]:
    """Return platform_fib acorn column definitions."""
    cols = [Column(name="asset_name", description="Asset name, joinable with asset_basics.name")]
    for i in range(MAX_FIBERS):
        cols.append(
            Column(
                name=f"fiber_{i}_targeted_structure",
                description=f"CCF acronym of the primary targeted brain structure for fiber {i}",
            )
        )
        cols.append(
            Column(
                name=f"fiber_{i}_intended_measurement",
                description=f"Intended measurement of the channel attached to fiber {i} (e.g. DA, 5-HT)",
            )
        )
    return cols
