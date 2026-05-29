"""Build per-platform QC tables (tag-level statuses) and upload to S3.

Usage:
    python scripts/build_platform_qc.py [--platform spim|fib|vr|dynamic_foraging]
"""

import argparse
import logging

from zombie_squirrel.acorn_helpers.platform_qc import PLATFORMS
from zombie_squirrel.acorns import ACORN_REGISTRY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=PLATFORMS, help="Build only this platform")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    platform_qc = ACORN_REGISTRY["platform_qc"]
    targets = [args.platform] if args.platform else PLATFORMS

    for platform in targets:
        logging.info(f"Building platform_qc/{platform}...")
        df = platform_qc(platform=platform, force_update=True)
        logging.info(f"  Done: {len(df)} rows, {df['asset_name'].nunique() if not df.empty else 0} assets")

    logging.info("Done.")


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
