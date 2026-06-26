"""Build dynamic foraging platform cache tables (sessions + per-subject trials/events).

Force-updates the three `platform_dynamic_foraging_*` cache tables by reading
the upstream `aind-dynamic-foraging-database` parquet bucket via DuckDB and
re-publishing the data into the active biodata-cache backend.

Usage:
    python scripts/build_platform_df.py
    python scripts/build_platform_df.py --skip-trials --skip-events
    python scripts/build_platform_df.py --subjects 754372 758435
    python scripts/build_platform_df.py --max-workers 16
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
from aind_dynamic_foraging_database import EVENT_DB, TRIAL_DB

from biodata_cache.registry import NAMES, TABLE_REGISTRY


_TABLE_BASES = {
    "df_trials": TRIAL_DB,
    "df_events": EVENT_DB,
}


def _build_sessions() -> list[str]:
    sessions_fn = TABLE_REGISTRY[NAMES["df_sessions"]]
    logging.info(f"Building {NAMES['df_sessions']}...")
    df = sessions_fn(force_update=True)
    subject_ids = sorted({str(s) for s in df["subject_id"].dropna().unique()})
    logging.info(f"  Done: {len(df)} sessions across {len(subject_ids)} subjects")
    return subject_ids


def _upstream_partition_subjects(base: str) -> set[str]:
    """Return the set of subject_ids that actually have a partition file under `base`."""
    with duckdb.connect() as con:
        rows = con.sql(f"SELECT file FROM glob('{base}/subject_id=*/*.parquet')").df()
    found = rows["file"].str.extract(r"subject_id=([^/]+)/")[0].dropna()
    return set(found)


def _build_per_subject(table_key: str, subject_ids: list[str], max_workers: int) -> None:
    fn = TABLE_REGISTRY[NAMES[table_key]]
    table_name = NAMES[table_key]

    available = _upstream_partition_subjects(_TABLE_BASES[table_key])
    requested = list(subject_ids)
    targets = [s for s in requested if s in available]
    missing = [s for s in requested if s not in available]
    logging.info(
        f"Building {table_name} for {len(targets)} subjects "
        f"({len(missing)} skipped — no upstream partition; max_workers={max_workers})..."
    )

    successes = 0
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_subject = {
            executor.submit(fn, subject_id=subject_id, force_update=True): subject_id for subject_id in targets
        }
        for future in as_completed(future_to_subject):
            subject_id = future_to_subject[future]
            try:
                df = future.result()
                successes += 1
                logging.info(f"  {table_name}/{subject_id}: {len(df)} rows")
            except Exception as e:
                failures.append((subject_id, str(e)))
                logging.warning(f"  {table_name}/{subject_id}: FAILED ({e})")

    logging.info(f"  Done: {successes} succeeded, {len(failures)} failed, {len(missing)} skipped")
    if failures:
        for subject_id, err in failures:
            logging.warning(f"    failed subject {subject_id}: {err}")
    if missing:
        logging.info(f"    skipped (no upstream partition): {', '.join(missing)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-sessions", action="store_true", help="Skip the session table build")
    parser.add_argument("--skip-trials", action="store_true", help="Skip the per-subject trials build")
    parser.add_argument("--skip-events", action="store_true", help="Skip the per-subject events build")
    parser.add_argument(
        "--subjects",
        nargs="+",
        default=None,
        help="Restrict per-subject builds to these subject IDs (default: all from the session table)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Worker threads for per-subject trial/event fetches (default: 8)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.skip_sessions and args.subjects is None and not (args.skip_trials and args.skip_events):
        sessions_fn = TABLE_REGISTRY[NAMES["df_sessions"]]
        df = sessions_fn()
        subject_ids = sorted({str(s) for s in df["subject_id"].dropna().unique()})
        logging.info(f"Loaded {len(subject_ids)} subjects from cached session table")
    elif args.skip_sessions:
        subject_ids = [str(s) for s in (args.subjects or [])]
    else:
        all_subject_ids = _build_sessions()
        subject_ids = [str(s) for s in args.subjects] if args.subjects else all_subject_ids

    if not args.skip_trials and subject_ids:
        _build_per_subject("df_trials", subject_ids, args.max_workers)

    if not args.skip_events and subject_ids:
        _build_per_subject("df_events", subject_ids, args.max_workers)

    logging.info("Done.")


if __name__ == "__main__":
    main()
