"""Scientist RL FIB cohort summary cache table.

One row per (fiber_targeted_structure, virus) combination, collapsed across all
qualifying subjects. Fibers are matched to brain injections at the same targeted
structure. The indicator column is a placeholder (virus_tars_id) until a
virus->indicator mapping is available.
"""

import logging
from collections import defaultdict

import pandas as pd
from aind_data_access_api.document_db import MetadataDbClient

import biodata_cache.registry as registry
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

BATCH_SIZE = 100

TABLE_NAME = "scientist_rl_fib"

_FILTER = {
    "data_description.modalities.abbreviation": {"$all": ["behavior", "fib"]},
    "data_description.data_level": "derived",
    "acquisition.stimulus_epochs.performance_metrics.output_parameters.task_parameters.stage_in_use": {
        "$in": ["STAGE_FINAL", "GRADUATED"]
    },
}


def _fetch_records() -> list[dict]:
    """Fetch all matching records with name, subject_id, and procedures."""
    client = MetadataDbClient(host=registry.API_GATEWAY_HOST, version="v2")
    projection = {
        "name": 1,
        "subject.subject_id": 1,
        "procedures.subject_procedures": 1,
        "_id": 0,
    }
    return client.retrieve_docdb_records(
        filter_query=_FILTER,
        projection=projection,
        limit=0,
    )


def _extract_fiber_implants(record: dict) -> list[dict]:
    """Extract fiber implant targeted structures and coordinates from procedures.

    Returns a list of dicts with 'targeted_structure' and 'coordinates' keys.
    """
    implants = []
    for subject_proc in (record.get("procedures") or {}).get("subject_procedures") or []:
        for proc in subject_proc.get("procedures") or []:
            if proc.get("object_type") != "Probe implant":
                continue
            config = proc.get("device_config") or {}
            targeted = config.get("primary_targeted_structure") or {}
            acronym = targeted.get("acronym") or "missing"
            if acronym == "root":
                acronym = "missing"
            coords = _extract_coordinates(config)
            implants.append({"targeted_structure": acronym, "coordinates": coords})
    return implants


def _extract_coordinates(config: dict) -> str:
    """Extract AP, ML, Depth from probe config transform as a formatted string."""
    for item in config.get("transform") or []:
        if item.get("object_type") == "Translation":
            t = item.get("translation") or []
            if len(t) >= 4:
                return f"AP={t[0]}, ML={float(t[1])}, D={t[3]}"
    return "missing"


def _extract_brain_injections(record: dict) -> list[dict]:
    """Extract brain injection targeted structures and virus IDs from procedures.

    Returns a list of dicts with 'targeted_structure' and 'viruses' (list) keys.
    Names are deduplicated per injection entry.
    """
    injections = []
    for subject_proc in (record.get("procedures") or {}).get("subject_procedures") or []:
        for proc in subject_proc.get("procedures") or []:
            if proc.get("object_type") != "Brain injection":
                continue
            targeted = proc.get("targeted_structure") or {}
            acronym = targeted.get("acronym") or "missing"
            if acronym == "root":
                acronym = "missing"
            viruses = []
            for material in proc.get("injection_materials") or []:
                virus_id = material.get("name")
                if virus_id and virus_id not in viruses:
                    viruses.append(virus_id)
            if viruses:
                injections.append({"targeted_structure": acronym, "viruses": viruses})
    return injections


def _get_fiber_injection_pairs(
    implants: list[dict], injections: list[dict]
) -> list[tuple[str, str, str]]:
    """Match fiber implants to brain injections at the same targeted structure.

    Returns list of (targeted_structure, coordinate_str, virus_tars_id) tuples.
    Only fibers whose targeted_structure matches a brain injection site are included.
    Viruses are deduplicated across multiple injections at the same structure.
    """
    injection_map: dict[str, list[str]] = defaultdict(list)
    for injection in injections:
        structure = injection["targeted_structure"]
        for virus in injection["viruses"]:
            if virus not in injection_map[structure]:
                injection_map[structure].append(virus)

    seen: set[tuple[str, str, str]] = set()
    pairs = []
    for implant in implants:
        structure = implant["targeted_structure"]
        coords = implant["coordinates"]
        for virus in injection_map.get(structure, []):
            key = (structure, coords, virus)
            if key not in seen:
                seen.add(key)
                pairs.append(key)
    return pairs


def _build_rows(records: list[dict]) -> list[dict]:
    """Build cohort summary rows collapsed across subjects.

    Groups records by subject_id, counts sessions per subject, extracts one set
    of procedures per subject, then collapses to one row per
    (fiber_targeted_structure, virus) key.
    """
    subject_records: dict[str, dict] = {}
    subject_session_counts: dict[str, int] = {}

    for record in records:
        subject_id = (record.get("subject") or {}).get("subject_id") or "missing"
        subject_session_counts[subject_id] = subject_session_counts.get(subject_id, 0) + 1
        if subject_id not in subject_records:
            subject_records[subject_id] = record

    group_map: dict[tuple[str, str, str], dict] = {}

    for subject_id, record in subject_records.items():
        implants = _extract_fiber_implants(record)
        injections = _extract_brain_injections(record)
        pairs = _get_fiber_injection_pairs(implants, injections)

        for structure, coords, virus in pairs:
            key = (structure, coords, virus)
            if key not in group_map:
                group_map[key] = {
                    "targeted_structure": structure,
                    "coordinates": coords,
                    "indicator": virus,
                    "subject_ids": set(),
                }
            group_map[key]["subject_ids"].add(subject_id)

    rows = []
    for (structure, coords, virus), data in sorted(group_map.items()):
        subject_ids_sorted = sorted(data["subject_ids"])
        session_count = sum(subject_session_counts.get(s, 0) for s in subject_ids_sorted)
        rows.append(
            {
                "targeted_structure": structure,
                "coordinates": coords,
                "indicator": virus,
                "mouse_ids": subject_ids_sorted,
                "mouse_count": len(subject_ids_sorted),
                "session_count": session_count,
            }
        )

    return rows


@registry.register_table(TABLE_NAME)
def scientist_rl_fib(force_update: bool = False) -> pd.DataFrame:
    """Build a cohort summary for scientist RL FIB mice.

    One row per (fiber_targeted_structure, virus) combination collapsed across all
    subjects with behavior+fib derived assets at STAGE_FINAL or GRADUATED using
    main or production_testing software branches.

    Fiber implants are matched to brain injections at the same targeted_structure.
    The indicator column uses virus_tars_id as a placeholder until a
    virus->indicator mapping is available.

    Args:
        force_update: If True, bypass cache and rebuild from database.

    Returns:
        DataFrame with columns: targeted_structure, coordinates, indicator,
        mouse_ids, mouse_count, session_count.
    """
    df = registry.BACKEND.read(TABLE_NAME)

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from database.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            CacheLogMessage(
                backend=registry.BACKEND.__class__.__name__,
                table=TABLE_NAME,
                message="Updating cache",
            ).to_json()
        )

        records = _fetch_records()
        rows = _build_rows(records)
        df = pd.DataFrame(rows)
        registry.BACKEND.write(TABLE_NAME, df)

    return df


def scientist_rl_fib_columns() -> list[Column]:
    """Return scientist_rl_fib cache table column definitions."""
    return [
        Column(
            name="targeted_structure",
            description="CCF acronym of the fiber implant primary targeted structure",
        ),
        Column(
            name="coordinates",
            description="AP/ML/Depth implant coordinate string",
        ),
        Column(
            name="indicator",
            description="Name of the injection material from brain injection at the matched targeted structure",
        ),
        Column(
            name="mouse_ids",
            description="Sorted list of subject IDs sharing this targeted_structure + indicator combination",
        ),
        Column(name="mouse_count", description="Number of subjects"),
        Column(name="session_count", description="Total qualifying sessions across all subjects in mouse_ids"),
    ]
