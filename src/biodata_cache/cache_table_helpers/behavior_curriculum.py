"""Behavior curriculum cache table."""

import json
import logging

import boto3
import pandas as pd

import biodata_cache.registry as registry
from biodata_cache.cache_table_helpers.asset_basics import asset_basics
from biodata_cache.models import Column
from biodata_cache.utils import CacheLogMessage, setup_logging

AIND_OPEN_DATA_BUCKET = "aind-open-data"


def _find_trainer_state_key(s3_client, bucket: str, asset_key: str) -> str | None:
    """Return the S3 key of the first trainer_state JSON found for an asset.

    Checks the new standard location first, then falls back to the legacy
    launcher directory used by older assets.
    """
    for prefix in (
        f"{asset_key}/behavior/trainer_state",
        f"{asset_key}/behavior/Logs/.launcher/TrainerState_",
    ):
        result = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
        for obj in result.get("Contents", []):
            if obj["Key"].endswith(".json"):
                return obj["Key"]
    return None


def _parse_trainer_state(s3_client, bucket: str, key: str) -> tuple[str | None, str | None, int | None]:
    """Download and parse a TrainerState JSON; return (curriculum_name, stage_name, stage_node_id)."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response["Body"].read())
        curriculum_name = data.get("curriculum", {}).get("name")
        stage_name = data.get("stage", {}).get("name")
        node_id = None
        if stage_name:
            for k, v in (data.get("curriculum", {}).get("graph", {}).get("nodes", {}) or {}).items():
                if v.get("name") == stage_name:
                    try:
                        node_id = int(k)
                    except (ValueError, TypeError):
                        pass
                    break
        return curriculum_name, stage_name, node_id
    except Exception:
        return None, None, None


CHECKPOINT_INTERVAL = 500


@registry.register_table(registry.NAMES["curriculum"])
def behavior_curriculum(force_update: bool = False) -> pd.DataFrame:
    """Build a DataFrame of behavior assets with curriculum name and stage.

    One row per behavior asset. Reads trainer_state JSON from S3 for each asset,
    checking the new standard location (behavior/trainer_state*.json) and the
    legacy location (behavior/Logs/.launcher/TrainerState_*.json). Assets with
    no trainer state file get None for curriculum_name and stage_name.

    Incremental: already-processed assets are skipped even when force_update=True,
    since trainer state is immutable per asset. Progress is checkpointed every
    500 newly processed assets so interrupted runs can resume cheaply.

    Args:
        force_update: If True, process new assets not yet in the cache.

    Returns:
        DataFrame with columns: asset_name, curriculum_name, stage_name, stage_node_id.
    """
    df = registry.BACKEND.read(registry.NAMES["curriculum"])

    if df.empty and not force_update:
        raise ValueError("Cache is empty. Use force_update=True to fetch data from S3.")

    basics = asset_basics()
    behavior_assets = basics[
        basics["modalities"].apply(
            lambda x: x is not None and not isinstance(x, float) and any("behavior" in m.lower() for m in x)
        )
    ]

    # Rows with curriculum data but no stage_node_id are from before this column was added — reprocess them.
    if not df.empty and "stage_node_id" not in df.columns:
        df["stage_node_id"] = None
    incomplete = (
        set(df[df["curriculum_name"].notna() & df["stage_node_id"].isna()]["asset_name"].dropna())
        if not df.empty
        else set()
    )
    known_names = (set(df["asset_name"].dropna()) if not df.empty else set()) - incomplete
    if incomplete:
        df = df[df["asset_name"].isin(known_names)]
    new_assets = behavior_assets[~behavior_assets["name"].isin(known_names)]

    if new_assets.empty:
        return df

    setup_logging()
    logging.info(
        CacheLogMessage(
            backend=registry.BACKEND.__class__.__name__,
            table=registry.NAMES["curriculum"],
            message=f"Processing {len(new_assets)} new behavior assets ({len(known_names)} already cached)",
        ).to_json()
    )

    s3_client = boto3.client("s3")
    new_rows: list[dict] = []

    for i, (_, row) in enumerate(new_assets.iterrows()):
        asset_name = row.get("name")
        location = row.get("location") or ""
        asset_key = location.removeprefix(f"s3://{AIND_OPEN_DATA_BUCKET}/")

        if not location.startswith(f"s3://{AIND_OPEN_DATA_BUCKET}/"):
            new_rows.append(
                {"asset_name": asset_name, "curriculum_name": None, "stage_name": None, "stage_node_id": None}
            )
        else:
            key = _find_trainer_state_key(s3_client, AIND_OPEN_DATA_BUCKET, asset_key)
            if key is None:
                new_rows.append(
                    {"asset_name": asset_name, "curriculum_name": None, "stage_name": None, "stage_node_id": None}
                )
            else:
                curriculum_name, stage_name, stage_node_id = _parse_trainer_state(s3_client, AIND_OPEN_DATA_BUCKET, key)
                new_rows.append(
                    {
                        "asset_name": asset_name,
                        "curriculum_name": curriculum_name or None,
                        "stage_name": stage_name or None,
                        "stage_node_id": stage_node_id,
                    }
                )

        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            checkpoint_df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
            registry.BACKEND.write(registry.NAMES["curriculum"], checkpoint_df)
            logging.info(
                CacheLogMessage(
                    backend=registry.BACKEND.__class__.__name__,
                    table=registry.NAMES["curriculum"],
                    message=f"Checkpoint: saved {i + 1} / {len(new_assets)} new assets",
                ).to_json()
            )

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    registry.BACKEND.write(registry.NAMES["curriculum"], df)

    return df


def behavior_curriculum_columns() -> list[Column]:
    """Return behavior_curriculum cache table column definitions."""
    return [
        Column(name="asset_name", description="Asset name, joinable with asset_basics.name"),
        Column(name="curriculum_name", description="Curriculum name from trainer_state.json; null if not found"),
        Column(name="stage_name", description="Stage name from trainer_state.json; null if not found"),
        Column(
            name="stage_node_id",
            description="Integer node ID of the current stage in the curriculum graph; use for ordering stages",
        ),
    ]
