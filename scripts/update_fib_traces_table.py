"""Update the fiber photometry dF/F trace cache table for all fib assets."""

from biodata_cache.registry import NAMES, TABLE_REGISTRY


def main():
    """Update the platform_fib_traces cache table for every derived fib asset."""
    df_basics = TABLE_REGISTRY[NAMES["basics"]](force_update=False)

    fib_mask = df_basics["modalities"].apply(
        lambda x: x is not None and not isinstance(x, float) and any("fib" in m.lower() for m in x)
    )
    asset_names = df_basics[fib_mask & (df_basics["data_level"] == "derived")]["name"].dropna().unique()
    print(f"Found {len(asset_names)} derived fiber photometry assets.")

    fib_traces_fn = TABLE_REGISTRY[NAMES["fib_traces"]]

    for i, asset_name in enumerate(asset_names, 1):
        fib_traces_fn(asset_name=asset_name, force_update=True)
        print(f"[{i}/{len(asset_names)}] Done: {asset_name}")

    print("Fiber photometry trace cache update complete.")


if __name__ == "__main__":
    main()
