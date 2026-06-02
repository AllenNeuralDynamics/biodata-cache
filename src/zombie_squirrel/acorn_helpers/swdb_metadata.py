"""SWDB metadata acorn: per-project metadata tables for the Summer Workshop on the Dynamic Brain."""

import logging
from datetime import datetime

import pandas as pd
from aind_data_access_api.document_db import MetadataDbClient

import zombie_squirrel.acorns as acorns
from zombie_squirrel.squirrel import Column
from zombie_squirrel.utils import SquirrelMessage, setup_logging

DATASETS = ["v1dd", "bci", "dynamic_foraging", "np_ultra"]

BATCH_SIZE = 50

BCI_PROBLEM_ASSETS = [
    "single-plane-ophys_731015_2025-01-28_17-40-57_processed_2025-08-04_04-38-08",
    "single-plane-ophys_772414_2025-02-04_13-21-29_processed_2025-08-12_06-14-42",
]

NP_ULTRA_SALINE_EPOCHS = [
    "Spontaneous_0", "RFMapping_0", "OptoTagging_0", "Injection",
    "Spontaneous_1", "RFMapping_1", "OptoTagging_1",
    "Spontaneous_2", "RFMapping_2", "OptoTagging_2", "Anesthesia",
    "Spontaneous_3", "RFMapping_3", "Spontaneous_4",
]

NP_ULTRA_PSILO_EPOCHS = [
    "Spontaneous_0", "RFMapping_0", "OptoTagging_0", "Injection",
    "Spontaneous_1", "RFMapping_1", "OptoTagging_1",
    "Spontaneous_2", "RFMapping_2", "OptoTagging_2",
]

DATASET_FILTERS = {
    "v1dd": {
        "data_description.project_name": "V1 Deep Dive",
    },
    "bci": {
        "acquisition.acquisition_type": "BCI single neuron stim",
        "data_description.data_level": "derived",
        "processing.processing_pipeline.data_processes.start_date_time": {"$gte": "2025-08-03"},
    },
    "dynamic_foraging": {
        "acquisition.acquisition_start_time": {"$regex": "^2025"},
        "data_description.modalities.abbreviation": {"$nin": ["ecephys", "fib"]},
        "data_description.data_level": "derived",
        "data_description.project_name": "Behavior Platform",
        "procedures": {"$ne": None},
        "quality_control.status": {"$exists": True, "$ne": None},
    },
    "np_ultra": {
        "data_description.project_name": "NP Ultra and Psychedelics",
        "data_description.data_level": "derived",
    },
}


@acorns.register_acorn(acorns.NAMES["swdb"])
def swdb_metadata(dataset: str, force_update: bool = False) -> pd.DataFrame:
    """Build a metadata table for a SWDB project dataset.

    One row per data asset with subject, session, and project-specific fields.
    Results are cached per dataset.

    Args:
        dataset: One of 'v1dd', 'bci', 'dynamic_foraging', 'np_ultra'.
        force_update: If True, bypass cache and rebuild from database.

    Returns:
        DataFrame with columns specific to the requested dataset.

    Raises:
        ValueError: If dataset is not recognized or cache is empty without force_update.
    """
    if dataset not in DATASETS:
        raise ValueError(f"Unknown dataset '{dataset}'. Must be one of {DATASETS}.")

    cache_key = f"swdb_metadata/{dataset}"
    df = acorns.TREE.scurry(cache_key)

    if df.empty and not force_update:
        raise ValueError(f"Cache is empty for dataset '{dataset}'. Use force_update=True to rebuild.")

    if df.empty or force_update:
        setup_logging()
        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn=acorns.NAMES["swdb"],
                message=f"Building SWDB metadata for '{dataset}'",
            ).to_json()
        )
        df = _build(dataset)
        if not df.empty:
            acorns.TREE.hide(cache_key, df)

    return df


def _build(dataset: str) -> pd.DataFrame:
    """Build the metadata DataFrame for the given dataset."""
    client = MetadataDbClient(
        host=acorns.API_GATEWAY_HOST,
        version="v2",
    )
    ids = _get_ids(client, DATASET_FILTERS[dataset])
    if not ids:
        return pd.DataFrame()
    records = _fetch_records(client, ids, dataset)
    if dataset == "v1dd":
        return _build_v1dd(records)
    if dataset == "bci":
        return _build_bci(records)
    if dataset == "dynamic_foraging":
        return _build_dynamic_foraging(records)
    if dataset == "np_ultra":
        return _build_np_ultra(records)
    return pd.DataFrame()


def _get_ids(client: MetadataDbClient, filter_query: dict) -> list[str]:
    """Fetch the _id values of all records matching filter_query."""
    records = client.retrieve_docdb_records(
        filter_query=filter_query,
        projection={"_id": 1},
        limit=0,
    )
    return [r["_id"] for r in records]


def _fetch_records(client: MetadataDbClient, ids: list[str], dataset: str) -> list[dict]:
    """Fetch full records for the given _id list in batches of BATCH_SIZE."""
    records = []
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i: i + BATCH_SIZE]
        logging.info(
            SquirrelMessage(
                tree=acorns.TREE.__class__.__name__,
                acorn=acorns.NAMES["swdb"],
                message=f"Fetching {dataset} batch {i // BATCH_SIZE + 1} / {-(-len(ids) // BATCH_SIZE)}",
            ).to_json()
        )
        batch_records = client.retrieve_docdb_records(
            filter_query={"_id": {"$in": batch}},
            limit=0,
        )
        records.extend(batch_records)
    return records


def _get(obj: dict, *path, default=None):
    """Safely navigate a nested dict, returning default if any key is missing."""
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
        if obj is None:
            return default
    return obj


def _first_modality_name(record: dict) -> str | None:
    """Return the name of the first entry in data_description.modalities."""
    entries = _get(record, "data_description", "modalities", default=[]) or []
    if entries and isinstance(entries[0], dict):
        return entries[0].get("name")
    return None


def _to_datetime(x) -> datetime | None:
    """Coerce a value to datetime, handling strings, existing datetimes, and None."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, datetime):
        return x
    return datetime.fromisoformat(str(x))


def _parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Parse session_time into session_date and time, parse date_of_birth, compute age in days."""
    df = df.copy()
    df = df.dropna(subset=["session_time"]).reset_index(drop=True)
    parsed = df["session_time"].apply(_to_datetime)
    df["session_date"] = parsed.apply(lambda x: x.date() if x is not None else None)
    df["session_time"] = parsed.apply(lambda x: x.time() if x is not None else None)
    df["date_of_birth"] = df["date_of_birth"].apply(
        lambda x: datetime.strptime(x, "%Y-%m-%d").date()
        if x and not (isinstance(x, float) and pd.isna(x))
        else None
    )
    df["age"] = df.apply(
        lambda x: (x["session_date"] - x["date_of_birth"]).days
        if x["session_date"] is not None and x["date_of_birth"] is not None
        else None,
        axis=1,
    )
    return df


def _reorder(df: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    """Subset and reorder columns, skipping any that are absent."""
    return df[[c for c in order if c in df.columns]]


def _build_v1dd(records: list[dict]) -> pd.DataFrame:
    """Extract V1 Deep Dive fields from full records."""
    rows = []
    for record in records:
        tags = _get(record, "data_description", "tags", default=[]) or []
        modalities = _get(record, "data_description", "modalities", default=[]) or []
        row = {
            "_id": record["_id"],
            "name": record.get("name"),
            "subject_id": _get(record, "data_description", "subject_id"),
            "genotype": _get(record, "subject", "subject_details", "genotype"),
            "date_of_birth": _get(record, "subject", "subject_details", "date_of_birth"),
            "sex": _get(record, "subject", "subject_details", "sex"),
            "session_time": _get(record, "acquisition", "acquisition_start_time"),
            "project_name": _get(record, "data_description", "project_name"),
            "modality": [m.get("name") for m in modalities if isinstance(m, dict)],
            "column": tags[0] if len(tags) > 0 else None,
            "volume": tags[1] if len(tags) > 1 else None,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = _parse_dates(df)
    df["column"] = df["column"].apply(lambda x: int(x.split(" ")[-1]) if x else None)
    df["volume"] = df["volume"].apply(lambda x: int(x.split(" ")[-1]) if x else None)
    df["golden_mouse"] = False
    df.loc[df["subject_id"] == "409828", "golden_mouse"] = True

    order = [
        "project_name", "_id", "name", "subject_id", "golden_mouse", "genotype",
        "date_of_birth", "sex", "modality", "session_date", "age", "session_time",
        "column", "volume",
    ]
    return _reorder(df, order)


def _extract_bci_virus(record: dict) -> str | None:
    """Extract the first injection material name from procedures."""
    for sp in _get(record, "procedures", "subject_procedures", default=[]) or []:
        for proc in sp.get("procedures", []) or []:
            for mat in proc.get("injection_materials", []) or []:
                if isinstance(mat, dict) and mat.get("name"):
                    return mat["name"]
    return None


def _extract_bci_targeted_structure(record: dict) -> str | None:
    """Extract the first targeted_structure from session data_streams."""
    for stream in _get(record, "session", "data_streams", default=[]) or []:
        ts = _get(stream, "stack_parameters", "targeted_structure")
        if ts:
            return ts
    return None


def _extract_bci_ophys_fov(record: dict) -> str | None:
    """Extract the first ophys FOV note from session data_streams."""
    for stream in _get(record, "session", "data_streams", default=[]) or []:
        for fov in stream.get("ophys_fovs", []) or []:
            note = fov.get("notes") if isinstance(fov, dict) else None
            if note:
                return note
    return None


def _build_bci(records: list[dict]) -> pd.DataFrame:
    """Extract BCI single neuron stim fields from full records."""
    rows = []
    for record in records:
        epochs = _get(record, "session", "stimulus_epochs", default=[]) or []
        session_number = next(
            (e.get("session_number") for e in epochs if e.get("stimulus_name") == "single neuron BCI conditioning"),
            None,
        )
        row = {
            "_id": record["_id"],
            "name": record.get("name"),
            "subject_id": _get(record, "data_description", "subject_id"),
            "genotype": _get(record, "subject", "genotype"),
            "virus": _extract_bci_virus(record),
            "date_of_birth": _get(record, "subject", "date_of_birth"),
            "sex": _get(record, "subject", "sex"),
            "session_type": _get(record, "acquisition", "acquisition_type"),
            "session_time": _get(record, "acquisition", "acquisition_start_time"),
            "stimulus_epochs": [e.get("stimulus_name") for e in epochs if isinstance(e, dict)],
            "project_name": _get(record, "data_description", "project_name"),
            "modality": _first_modality_name(record),
            "targeted_structure": _extract_bci_targeted_structure(record),
            "ophys_fov": _extract_bci_ophys_fov(record),
            "session_number": session_number,
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.drop_duplicates(subset="name")
    df = df[~df["name"].isin(BCI_PROBLEM_ASSETS)]
    df = _parse_dates(df)

    order = [
        "project_name", "session_type", "_id", "name", "subject_id", "genotype", "virus",
        "date_of_birth", "sex", "modality", "session_date", "age", "session_time",
        "targeted_structure", "ophys_fov", "session_number",
    ]
    return _reorder(df, order)


def _build_dynamic_foraging(records: list[dict]) -> pd.DataFrame:
    """Extract Dynamic Foraging (Behavior Platform) fields from full records."""
    rows = []
    for record in records:
        qc_status = _get(record, "quality_control", "status") or {}
        if not all(v == "Pass" for v in qc_status.values()):
            continue
        epochs = _get(record, "session", "stimulus_epochs", default=[]) or []
        first_epoch = epochs[0] if epochs else {}
        row = {
            "_id": record["_id"],
            "name": record.get("name"),
            "subject_id": _get(record, "data_description", "subject_id"),
            "genotype": _get(record, "subject", "genotype"),
            "date_of_birth": _get(record, "subject", "date_of_birth"),
            "sex": _get(record, "subject", "sex"),
            "session_type": _get(record, "acquisition", "acquisition_type"),
            "session_time": _get(record, "acquisition", "acquisition_start_time"),
            "project_name": _get(record, "data_description", "project_name"),
            "modality": _first_modality_name(record),
            "trials_total": first_epoch.get("trials_total"),
            "trials_rewarded": first_epoch.get("trials_rewarded"),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.drop_duplicates(subset="name")
    df = _parse_dates(df)

    order = [
        "project_name", "name", "subject_id", "genotype", "date_of_birth", "sex",
        "modality", "session_type", "session_date", "age", "session_time",
        "trials_total", "trials_rewarded",
    ]
    return _reorder(df, order)


def _build_np_ultra(records: list[dict]) -> pd.DataFrame:
    """Extract NP Ultra and Psychedelics fields from full records.

    Note: stimulus_epochs are assigned manually per subject because the metadata
    is incomplete in the database. Each subject is assumed to have exactly two
    sessions in sorted order: saline first, then psilocybin.
    """
    rows = []
    for record in records:
        epochs = _get(record, "acquisition", "stimulus_epochs", default=[]) or []
        row = {
            "_id": record["_id"],
            "name": record.get("name"),
            "subject_id": _get(record, "data_description", "subject_id"),
            "genotype": _get(record, "subject", "genotype"),
            "date_of_birth": _get(record, "subject", "date_of_birth"),
            "sex": _get(record, "subject", "sex"),
            "session_time": _get(record, "acquisition", "acquisition_start_time"),
            "stimulus_epochs": [e.get("stimulus_name") for e in epochs if isinstance(e, dict)],
            "project_name": _get(record, "data_description", "project_name"),
            "modality": _first_modality_name(record),
            "notes": [e.get("notes") for e in epochs if isinstance(e, dict)],
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.sort_values(by="session_time").reset_index(drop=True)
    n_subjects = len(df["subject_id"].unique())

    df["session_type"] = ["saline", "psilocybin"] * n_subjects
    df["stimulus_epochs"] = [NP_ULTRA_SALINE_EPOCHS, NP_ULTRA_PSILO_EPOCHS] * n_subjects

    sal_stim_types = sorted(set(s.split("_")[0] for s in NP_ULTRA_SALINE_EPOCHS))
    psi_stim_types = sorted(set(s.split("_")[0] for s in NP_ULTRA_PSILO_EPOCHS))
    df["stimulus_types"] = [sal_stim_types, psi_stim_types] * n_subjects

    df = _parse_dates(df)

    order = [
        "project_name", "_id", "name", "subject_id", "genotype", "date_of_birth",
        "sex", "modality", "session_date", "age", "session_time", "session_type",
        "stimulus_types", "notes",
    ]
    return _reorder(df, order)


def swdb_metadata_columns(dataset: str) -> list[Column]:
    """Return column definitions for the given SWDB dataset.

    Args:
        dataset: One of 'v1dd', 'bci', 'dynamic_foraging', 'np_ultra'.

    Returns:
        List of Column definitions for the dataset.
    """
    common = [
        Column(name="project_name", description="Project name from data_description"),
        Column(name="_id", description="MongoDB document ID"),
        Column(name="name", description="Data asset name"),
        Column(name="subject_id", description="Subject/mouse ID"),
        Column(name="genotype", description="Mouse genotype"),
        Column(name="date_of_birth", description="Date of birth (date)"),
        Column(name="sex", description="Subject sex"),
        Column(name="modality", description="Data modality name"),
        Column(name="session_date", description="Session date (date)"),
        Column(name="age", description="Age at session in days"),
        Column(name="session_time", description="Session start time (time)"),
    ]
    if dataset == "v1dd":
        return common + [
            Column(name="golden_mouse", description="True if subject_id is 409828 (golden mouse)"),
            Column(name="column", description="V1DD column number extracted from data_description.tags[0]"),
            Column(name="volume", description="V1DD volume number extracted from data_description.tags[1]"),
        ]
    if dataset == "bci":
        return [
            Column(name="project_name", description="Project name from data_description"),
            Column(name="session_type", description="Session type (BCI single neuron stim)"),
            Column(name="_id", description="MongoDB document ID"),
            Column(name="name", description="Data asset name"),
            Column(name="subject_id", description="Subject/mouse ID"),
            Column(name="genotype", description="Mouse genotype"),
            Column(name="virus", description="Injection material / virus name"),
            Column(name="date_of_birth", description="Date of birth (date)"),
            Column(name="sex", description="Subject sex"),
            Column(name="modality", description="Data modality name"),
            Column(name="session_date", description="Session date (date)"),
            Column(name="age", description="Age at session in days"),
            Column(name="session_time", description="Session start time (time)"),
            Column(name="targeted_structure", description="Targeted brain structure"),
            Column(name="ophys_fov", description="Notes from the ophys field-of-view"),
            Column(name="session_number", description="BCI conditioning session number"),
        ]
    if dataset == "dynamic_foraging":
        return [
            Column(name="project_name", description="Project name (Behavior Platform)"),
            Column(name="name", description="Data asset name"),
            Column(name="subject_id", description="Subject/mouse ID"),
            Column(name="genotype", description="Mouse genotype"),
            Column(name="date_of_birth", description="Date of birth (date)"),
            Column(name="sex", description="Subject sex"),
            Column(name="modality", description="Data modality name"),
            Column(name="session_type", description="Session type / task name"),
            Column(name="session_date", description="Session date (date)"),
            Column(name="age", description="Age at session in days"),
            Column(name="session_time", description="Session start time (time)"),
            Column(name="trials_total", description="Total number of trials in the session"),
            Column(name="trials_rewarded", description="Number of rewarded trials in the session"),
        ]
    if dataset == "np_ultra":
        return common + [
            Column(name="session_type", description="Session type: 'saline' or 'psilocybin'"),
            Column(name="stimulus_types", description="Unique stimulus type names for the session"),
            Column(name="notes", description="Notes from session stimulus epochs"),
        ]
    return []

