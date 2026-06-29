"""Update the fiber photometry dF/F trace cache table for all fib subjects."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from biodata_cache.registry import NAMES, TABLE_REGISTRY


def main():
    """Update the platform_fib_traces cache table for every subject with fib derived assets."""
    df_basics = TABLE_REGISTRY[NAMES["basics"]](force_update=False)

    fib_mask = df_basics["modalities"].apply(
        lambda x: x is not None and not isinstance(x, float) and any("fib" in m.lower() for m in x)
    )
    subject_ids = df_basics[fib_mask & (df_basics["data_level"] == "derived")]["subject_id"].dropna().unique()
    print(f"Found {len(subject_ids)} subjects with fiber photometry derived assets.")

    fib_traces_fn = TABLE_REGISTRY[NAMES["fib_traces"]]

    try:
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(fib_traces_fn, subject_id=subject_id, force_update=True): subject_id
                for subject_id in subject_ids
            }
            for i, future in enumerate(as_completed(futures), 1):
                subject_id = futures[future]
                future.result()
                print(f"[{i}/{len(subject_ids)}] Done: {subject_id}")
    # no test coverage needed on exception
    except Exception:  # noqa: PERF203
        for subject_id in subject_ids:
            fib_traces_fn(subject_id=subject_id, force_update=True)

    print("Fiber photometry trace cache update complete.")


if __name__ == "__main__":
    main()
