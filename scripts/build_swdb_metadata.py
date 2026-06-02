"""Build SWDB metadata tables and upload to S3.

Usage:
    python scripts/build_swdb_metadata.py [--dataset v1dd|bci|dynamic_foraging|np_ultra]
"""

import argparse
import logging

from zombie_squirrel.acorn_helpers.swdb_metadata import DATASETS
from zombie_squirrel.acorns import ACORN_REGISTRY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=DATASETS, help="Build only this dataset")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    swdb_metadata = ACORN_REGISTRY["swdb_metadata"]
    targets = [args.dataset] if args.dataset else DATASETS

    for dataset in targets:
        logging.info(f"Building swdb_metadata/{dataset}...")
        df = swdb_metadata(dataset=dataset, force_update=True)
        logging.info(f"  Done: {len(df)} rows")

    logging.info("Done.")


if __name__ == "__main__":
    main()
