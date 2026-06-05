"""Platform fiber photometry acorn."""

import logging

import pandas as pd
from aind_data_access_api.document_db import MetadataDbClient

import zombie_squirrel.acorns as acorns
from zombie_squirrel.acorn_helpers.asset_basics import asset_basics
from zombie_squirrel.squirrel import Column
from zombie_squirrel.utils import SquirrelMessage, setup_logging

BATCH_SIZE = 100


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


def _normalize(name: str) -> str:
    """Normalize fiber name for comparison: replace spaces with underscores."""
    return name.replace(" ", "_")


def _extract_fiber_channel_entries(record: dict, fiber_names: set[str]) -> list[tuple[str, str, str, str]]:
    """Return (fiber, patch_cord, channel_name, intended_measurement) for every channel.

    Builds patch_cord -> fiber from connections, restricted to connections whose
    target_device normalizes to a known fiber name (avoids clobbering with detector
    connections, and handles space/underscore variants like 'Fiber 0' vs 'Fiber_0').
    The returned fiber is the canonical name from fiber_names (underscore form).
    """
    norm_to_fiber = {_normalize(f): f for f in fiber_names}
    entries: list[tuple[str, str, str, str]] = []
    for stream in (record.get("acquisition") or {}).get("data_streams") or []:
        patch_cord_to_fiber: dict[str, str] = {}
        for conn in stream.get("connections") or []:
            src = conn.get("source_device")
            tgt = conn.get("target_device")
            if src and tgt:
                canonical = norm_to_fiber.get(_normalize(tgt))
                if canonical:
                    patch_cord_to_fiber[src] = canonical
        for config in stream.get("configurations") or []:
            if config.get("object_type") != "Patch cord config":
                continue
            patch_cord = config.get("device_name") or "missing"
            fiber = patch_cord_to_fiber.get(patch_cord)
            if fiber is None:
                continue
            for ch in config.get("channels") or []:
                channel = ch.get("channel_name") or "missing"
                intended = ch.get("intended_measurement") or "missing"
                entries.append((fiber, patch_cord, channel, intended))
    return entries


def _extract_fiber_structure_map(record: dict) -> dict[str, str]:
    """Build a map of fiber name -> targeted_structure acronym from procedures.

    Walks through subject_procedures -> surgery procedures -> Probe implant entries.
    Missing acronyms and 'root' are replaced with 'missing'.
    """
    fiber_structure: dict[str, str] = {}
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
            acronym = targeted.get("acronym") or "missing"
            if acronym == "root":
                acronym = "missing"
            fiber_structure[fiber_name] = acronym
    return fiber_structure



def _build_fib_rows(records: list[dict]) -> list[dict]:
    """Build one row per (asset_name, fiber, channel) with intended_measurement and targeted_structure."""
    rows = []
    for record in records:
        asset_name = record.get("name")
        fiber_structure = _extract_fiber_structure_map(record)
        entries = _extract_fiber_channel_entries(record, set(fiber_structure.keys()))

        for fiber, patch_cord, channel, intended_measurement in entries:
            rows.append(
                {
                    "asset_name": asset_name,
                    "fiber": fiber,
                    "patch_cord": patch_cord,
                    "channel": channel,
                    "intended_measurement": intended_measurement,
                    "targeted_structure": fiber_structure.get(fiber, "missing"),
                }
            )
    return rows


@acorns.register_acorn(acorns.NAMES["fib"])
def platform_fib(force_update: bool = False) -> pd.DataFrame:
    """Build a long-form DataFrame of fiber photometry assets.

    One row per (asset_name, fiber, channel) with the intended measurement and primary
    targeted brain structure for that combination. Missing values are the string 'missing'.
    Melt to wide form in the downstream viewer. Results are cached.

    Args:
        force_update: If True, bypass cache and rebuild from database.

    Returns:
        DataFrame with columns: asset_name, fiber, patch_cord, channel,
        intended_measurement, targeted_structure.
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
        fib_assets = basics[basics["modalities"].apply(lambda x: x is not None and not isinstance(x, float) and any("fib" in m.lower() for m in x))]
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
    return [
        Column(name="asset_name", description="Asset name, joinable with asset_basics.name"),
        Column(name="fiber", description="Implanted fiber name (e.g. 'Fiber 0'), from connections target_device"),
        Column(name="patch_cord", description="Patch cord name (e.g. 'Patch Cord 0'), from Patch cord config device_name"),
        Column(name="channel", description="Channel name (e.g. 'Fiber_0_Green')"),
        Column(
            name="intended_measurement",
            description="Intended measurement for this fiber/channel (e.g. DA, 5-HT); 'missing' if unavailable",
        ),
        Column(
            name="targeted_structure",
            description="CCF acronym of the primary targeted brain structure; 'missing' if unavailable or 'root'",
        ),
    ]
