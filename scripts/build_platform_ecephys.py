"""Build the ecephys spike/unit cache tables (partitioned by asset_name).

Force-updates the `platform_ecephys_spikes` and `platform_ecephys_units` cache
tables by reading the sorted `/units` group from each derived ecephys asset's
NWB (Zarr) files on S3 and re-publishing the data into the active biodata-cache
backend. Assets without sorted units (pose tracking, facemap, etc.) are skipped
automatically.

Usage:
    python scripts/build_platform_ecephys.py
    python scripts/build_platform_ecephys.py --skip-units
    python scripts/build_platform_ecephys.py --assets ecephys_841364_..._sorted_...
    python scripts/build_platform_ecephys.py --skip-existing --max-workers 4
    python scripts/build_platform_ecephys.py --refresh-basics
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from biodata_cache.registry import BACKEND, NAMES, TABLE_REGISTRY


def _derived_ecephys_assets(refresh_basics: bool) -> tuple[list[str], dict[str, str]]:
    """Return derived ecephys asset names and a name -> S3 location map from asset_basics."""
    df_basics = TABLE_REGISTRY[NAMES["basics"]](force_update=refresh_basics)

    ecephys_mask = df_basics["modalities"].apply(
        lambda x: x is not None and not isinstance(x, float) and any("ecephys" in m.lower() for m in x)
    )
    derived = df_basics[ecephys_mask & (df_basics["data_level"] == "derived")]
    asset_names = derived["name"].dropna().unique().tolist()
    location_map = dict(zip(df_basics["name"], df_basics["location"], strict=False))
    return asset_names, location_map


def _build_table(
    table_key: str,
    asset_names: list[str],
    location_map: dict[str, str],
    max_workers: int,
    skip_existing: bool,
) -> None:
    """Force-update one ecephys table for the given assets, in parallel."""
    fn = TABLE_REGISTRY[NAMES[table_key]]
    table_name = NAMES[table_key]
    targets = asset_names
    if skip_existing:
        targets = [a for a in asset_names if not BACKEND.partition_exists(f"{table_name}/{a}")]
    skipped = len(asset_names) - len(targets)
    logging.info(
        f"Building {table_name} for {len(targets)} assets "
        f"({skipped} skipped — partition exists; max_workers={max_workers})..."
    )

    successes = 0
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_asset = {
            executor.submit(fn, asset_name=asset_name, location=location_map.get(asset_name), force_update=True): (
                asset_name
            )
            for asset_name in targets
        }
        for future in as_completed(future_to_asset):
            asset_name = future_to_asset[future]
            try:
                future.result()
                successes += 1
                logging.info(f"  {table_name}/{asset_name}: done")
            except Exception as e:
                failures.append((asset_name, str(e)))
                logging.warning(f"  {table_name}/{asset_name}: FAILED ({e})")

    logging.info(f"  Done: {successes} succeeded, {len(failures)} failed, {skipped} skipped")
    for asset_name, err in failures:
        logging.warning(f"    failed asset {asset_name}: {err}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-spikes", action="store_true", help="Skip the platform_ecephys_spikes build")
    parser.add_argument("--skip-units", action="store_true", help="Skip the platform_ecephys_units build")
    parser.add_argument(
        "--assets",
        nargs="+",
        default=None,
        help="Restrict builds to these asset names (default: all derived ecephys assets)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip assets whose partition already exists in the backend",
    )
    parser.add_argument(
        "--refresh-basics",
        action="store_true",
        help="Force-update asset_basics before selecting assets (default: use cached)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="Worker threads for per-asset fetches (default: 2)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    all_asset_names, location_map = _derived_ecephys_assets(args.refresh_basics)
    if args.assets:
        requested = set(args.assets)
        asset_names = [a for a in all_asset_names if a in requested]
        unknown = requested - set(all_asset_names)
        for name in sorted(unknown):
            logging.warning(f"Requested asset not a derived ecephys asset in asset_basics: {name}")
    else:
        asset_names = all_asset_names
    logging.info(f"Found {len(asset_names)} derived ecephys assets to build.")

    if not args.skip_spikes:
        _build_table("ecephys_spikes", asset_names, location_map, args.max_workers, args.skip_existing)

    if not args.skip_units:
        _build_table("ecephys_units", asset_names, location_map, args.max_workers, args.skip_existing)

    logging.info("Done.")


if __name__ == "__main__":
    main()
