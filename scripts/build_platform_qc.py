"""Build per-platform long-form QC tables and upload to S3.

Usage:
    python scripts/build_platform_qc.py [--platform spim|fib|vr|dynamic_foraging] [--dry-run]
"""

import argparse
import io
import logging

import boto3
import duckdb
import pyarrow.parquet as pq

S3_BUCKET = "allen-data-views"
S3_PREFIX = "data-asset-cache"
ASSET_BASICS_KEY = f"{S3_PREFIX}/zs_asset_basics.pqt"
QC_PREFIX = f"{S3_PREFIX}/zs_qc/"

PLATFORMS = {
    "spim": "modalities ILIKE '%SPIM%'",
    "fib": "modalities ILIKE '%fib%'",
    "vr": "acquisition_type = 'AindVrForaging'",
    "dynamic_foraging": "acquisition_type SIMILAR TO '(Uncoupled|Coupled)( Without)? Baiting'",
}


def list_qc_subject_ids(s3_client) -> set[str]:
    """Return subject_ids that have a QC parquet on S3."""
    paginator = s3_client.get_paginator("list_objects_v2")
    subject_ids = set()
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=QC_PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".pqt"):
                subject_ids.add(key.split("/")[-1].replace(".pqt", ""))
    return subject_ids


def build_platform_table(con, platform_filter: str, qc_urls: list[str]) -> duckdb.DuckDBPyRelation:
    """Build the long-form QC table for a single platform."""
    qc_url_list = ", ".join(f"'{u}'" for u in qc_urls)

    sql = f"""
    WITH filtered AS (
        SELECT name AS asset_name,
               subject_id,
               COALESCE(instrument_id, '(unknown)') AS instrument_id,
               COALESCE(experimenters, '(unknown)') AS experimenters,
               acquisition_start_time AS timestamp
        FROM asset_basics
        WHERE {platform_filter}
    ),
    unnested AS (
        SELECT asset_name,
               subject_id,
               instrument_id,
               TRIM(exp) AS experimenter,
               timestamp
        FROM filtered,
             UNNEST(STRING_SPLIT(experimenters, ',')) AS t(exp)
    )
    SELECT u.asset_name,
           u.subject_id,
           u.instrument_id,
           u.experimenter,
           q.name AS metric_name,
           q.status,
           u.timestamp
    FROM unnested u
    JOIN quality_control q ON q.asset_name = u.asset_name
    ORDER BY u.timestamp DESC, u.asset_name, q.name
    """

    con.execute(f"""
        CREATE OR REPLACE TABLE quality_control AS
        SELECT name,
               modality,
               stage,
               value,
               asset_name,
               subject_id,
               timestamp,
               COALESCE(status, 'unknown') AS status
        FROM read_parquet([{qc_url_list}], union_by_name=true)
    """)

    return con.execute(sql).fetchdf()


def upload_parquet(df, s3_client, key: str) -> None:
    """Upload a DataFrame as snappy-compressed parquet to S3."""
    import pyarrow as pa

    table = pa.Table.from_pandas(df, preserve_index=False)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    buf.seek(0)
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buf.read(),
        ContentType="application/octet-stream",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=list(PLATFORMS.keys()), help="Build only this platform")
    parser.add_argument("--dry-run", action="store_true", help="Print stats but don't upload")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    s3_client = boto3.client("s3")
    platforms = {args.platform: PLATFORMS[args.platform]} if args.platform else PLATFORMS

    logging.info("Listing QC subject files on S3...")
    available_subjects = list_qc_subject_ids(s3_client)
    logging.info(f"Found {len(available_subjects)} subjects with QC data")

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region = 'us-west-2';")

    asset_basics_url = f"s3://{S3_BUCKET}/{ASSET_BASICS_KEY}"
    con.execute(f"CREATE TABLE asset_basics AS SELECT * FROM read_parquet('{asset_basics_url}')")
    logging.info("Loaded asset_basics")

    for platform_key, platform_filter in platforms.items():
        logging.info(f"Building platform_qc_{platform_key}...")

        subject_ids_result = con.execute(f"""
            SELECT DISTINCT subject_id FROM asset_basics WHERE {platform_filter}
        """).fetchdf()
        platform_subjects = set(subject_ids_result["subject_id"].dropna().tolist())

        matching_subjects = platform_subjects & available_subjects
        if not matching_subjects:
            logging.warning(f"No QC data available for platform {platform_key}")
            continue

        qc_urls = [
            f"s3://{S3_BUCKET}/{QC_PREFIX}{sid}.pqt"
            for sid in sorted(matching_subjects)
        ]
        logging.info(f"  {len(matching_subjects)} subjects with QC data (of {len(platform_subjects)} total)")

        df = build_platform_table(con, platform_filter, qc_urls)
        logging.info(f"  Result: {len(df)} rows, {df['asset_name'].nunique()} assets")

        if args.dry_run:
            print(f"\n[{platform_key}] {len(df)} rows, columns: {df.columns.tolist()}")
            print(df.head(5).to_string())
        else:
            output_key = f"{S3_PREFIX}/zs_platform_qc_{platform_key}.pqt"
            upload_parquet(df, s3_client, output_key)
            logging.info(f"  Uploaded to s3://{S3_BUCKET}/{output_key}")

    con.close()
    logging.info("Done.")


if __name__ == "__main__":
    main()
