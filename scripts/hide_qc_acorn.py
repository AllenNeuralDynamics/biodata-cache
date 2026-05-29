"""Run the QC hide_acorn for all subjects without updating other acorns."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from zombie_squirrel.acorns import ACORN_REGISTRY, NAMES


def _check_subject_needs_update(subject_id: str, qc_acorn) -> tuple[str, bool]:
    """Check if a subject needs QC update."""
    try:
        df_qc = qc_acorn(subject_id=subject_id, force_update=False)
        if df_qc.empty or "status" not in df_qc.columns:
            return subject_id, True
        return subject_id, False
    except Exception:
        return subject_id, True


def main():
    """Hide QC acorn for all subjects."""
    df_basics = ACORN_REGISTRY[NAMES["basics"]](force_update=False)
    subject_ids = df_basics["subject_id"].dropna().unique()
    print(f"Found {len(subject_ids)} subjects. Filtering for subjects without status column...")

    subjects_to_update = []
    qc_acorn = ACORN_REGISTRY[NAMES["qc"]]
    try:
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(_check_subject_needs_update, subject_id, qc_acorn): subject_id for subject_id in subject_ids}
            for future in as_completed(futures):
                subject_id, needs_update = future.result()
                if needs_update:
                    subjects_to_update.append(subject_id)
                else:
                    print(f"Skipping {subject_id} (already has status column)")
    except Exception:
        subjects_to_update = list(subject_ids)

    print(f"Fetching QC data for {len(subjects_to_update)} subjects...")

    qc_acorn = ACORN_REGISTRY[NAMES["qc"]]
    try:
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(qc_acorn, subject_id=subject_id, force_update=True): subject_id
                for subject_id in subjects_to_update
            }
            for i, future in enumerate(as_completed(futures), 1):
                subject_id = futures[future]
                future.result()
                print(f"[{i}/{len(subjects_to_update)}] Done: {subject_id}")
    # no test coverage needed on exception
    except Exception:  # noqa: PERF203
        for subject_id in subjects_to_update:
            qc_acorn(subject_id=subject_id, force_update=True)

    print("QC cache update complete.")


if __name__ == "__main__":
    main()
