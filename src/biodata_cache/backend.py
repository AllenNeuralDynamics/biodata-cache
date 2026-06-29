"""Storage backend interfaces for caching data."""

import io
import json
import logging
from abc import ABC, abstractmethod

import boto3
import duckdb
import pandas as pd

from biodata_cache.utils import BDC_VERSION, CacheLogMessage

_CACHE_ROOT = "data-asset-cache"
_VERSION_FOLDER = f"bdc-v{BDC_VERSION}"

HIVE_PARTITION_KEYS = {
    "qc": "subject_id",
    "qc_tag_status": "subject_id",
    "platform_qc": "platform",
    "platform_dynamic_foraging_trials": "subject_id",
    "platform_dynamic_foraging_events": "subject_id",
    "platform_fib_traces": "subject_id",
}


class Backend(ABC):
    """Base class for a cache storage backend."""

    def __init__(self) -> None:
        """Initialize the Backend."""
        super().__init__()

    @abstractmethod
    def write(self, table_name: str, data: pd.DataFrame) -> None:
        """Write records to the cache."""
        pass  # pragma: no cover

    @abstractmethod
    def read(self, table_name: str | list[str]) -> pd.DataFrame:
        """Read records from the cache.

        Args:
            table_name: Single table name or list of table names.
                When a list is provided, merges all tables and adds
                an 'asset_name' column to differentiate sources.

        """
        pass  # pragma: no cover

    @abstractmethod
    def get_location(self, table_name: str, partitioned: bool = False) -> str:
        """Return the storage location string for a given table."""
        pass  # pragma: no cover

    @abstractmethod
    def put_json(self, key: str, data: str) -> None:
        """Write a JSON string to the storage root under the given key."""
        pass  # pragma: no cover

    @abstractmethod
    def get_json(self, key: str) -> str:
        """Read a JSON string from the storage root under the given key."""
        pass  # pragma: no cover

    @abstractmethod
    def get_versions_index(self) -> list[str]:
        """Return the list of all available version folders from cache_versions.json."""
        pass  # pragma: no cover


class S3Backend(Backend):
    """Stores and retrieves caches using AWS S3 with parquet files."""

    def __init__(self) -> None:
        """Initialize S3Backend with S3 client."""
        self.bucket = "allen-data-views"
        self.s3_client = boto3.client("s3")

    def write(self, table_name: str, data: pd.DataFrame) -> None:
        """Store DataFrame as parquet file in S3."""
        if "/" in table_name:
            base, value = table_name.split("/", 1)
            partition_key = HIVE_PARTITION_KEYS[base]
            s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{base}/{partition_key}={value}/data.pqt"
            json_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{base}.json"
        else:
            s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{table_name}.pqt"
            json_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{table_name}.json"

        parquet_buffer = io.BytesIO()
        data.to_parquet(parquet_buffer, index=False, compression="zstd")
        parquet_buffer.seek(0)

        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=s3_key,
            Body=parquet_buffer.getvalue(),
        )
        logging.info(
            CacheLogMessage(
                backend="S3Backend", table=table_name, message=f"Stored cache to s3://{self.bucket}/{s3_key}"
            ).to_json()
        )

        metadata = {"columns": data.columns.tolist()}
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=json_key,
            Body=json.dumps(metadata),
        )

    def read(self, table_name: str | list[str]) -> pd.DataFrame:
        """Fetch DataFrame from S3 parquet file(s).

        When given a list of table names, merges them using DuckDB
        and adds an 'asset_name' column.
        """
        if isinstance(table_name, list):
            return self._read_multiple(table_name)
        return self._read_single(table_name)

    def _read_single(self, table_name: str) -> pd.DataFrame:
        """Fetch a single table from S3."""
        if "/" in table_name:
            base, value = table_name.split("/", 1)
            partition_key = HIVE_PARTITION_KEYS[base]
            s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{base}/{partition_key}={value}/data.pqt"
        else:
            s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{table_name}.pqt"

        try:
            query = f"""
                SELECT * FROM read_parquet(
                    's3://{self.bucket}/{s3_key}'
                )
            """
            result = duckdb.query(query).to_df()
            logging.info(
                CacheLogMessage(
                    backend="S3Backend", table=table_name, message=f"Retrieved cache from s3://{self.bucket}/{s3_key}"
                ).to_json()
            )
            return result
        except Exception as e:
            logging.warning(
                CacheLogMessage(
                    backend="S3Backend", table=table_name, message=f"Error fetching from cache {s3_key}: {e}"
                ).to_json()
            )
            return pd.DataFrame()

    def get_location(self, table_name: str, partitioned: bool = False) -> str:
        """Return the S3 URI for a given table."""
        if partitioned:
            return f"s3://{self.bucket}/{_CACHE_ROOT}/{_VERSION_FOLDER}/{table_name}/"
        if "/" in table_name:
            base, value = table_name.split("/", 1)
            partition_key = HIVE_PARTITION_KEYS[base]
            return f"s3://{self.bucket}/{_CACHE_ROOT}/{_VERSION_FOLDER}/{base}/{partition_key}={value}/data.pqt"
        return f"s3://{self.bucket}/{_CACHE_ROOT}/{_VERSION_FOLDER}/{table_name}.pqt"

    def put_json(self, key: str, data: str) -> None:  # pragma: no cover
        """Write a JSON string to the versioned folder in S3 and update the index."""
        s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{key}"
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=s3_key,
            Body=data.encode(),
            ContentType="application/json",
        )
        logging.info(
            CacheLogMessage(
                backend="S3Backend", table=key, message=f"Published metadata to s3://{self.bucket}/{s3_key}"
            ).to_json()
        )
        index_key = f"{_CACHE_ROOT}/cache_versions.json"
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=index_key)
            existing = json.loads(response["Body"].read().decode())
        except Exception:
            existing = []
        if _VERSION_FOLDER not in existing:
            existing.append(_VERSION_FOLDER)
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=index_key,
            Body=json.dumps(existing).encode(),
            ContentType="application/json",
        )

    def get_json(self, key: str) -> str:  # pragma: no cover
        """Read a JSON string from the versioned folder in S3."""
        s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{key}"
        response = self.s3_client.get_object(Bucket=self.bucket, Key=s3_key)
        return response["Body"].read().decode()

    def get_versions_index(self) -> list[str]:  # pragma: no cover
        """Return the list of all available version folders from the top-level cache_versions.json."""
        index_key = f"{_CACHE_ROOT}/cache_versions.json"
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=index_key)
            return json.loads(response["Body"].read().decode())
        except Exception:
            return []

    def _read_multiple(self, table_names: list[str]) -> pd.DataFrame:
        """Fetch and merge multiple tables from S3."""
        parquet_paths = []
        asset_names = []

        for tbl_name in table_names:
            s3_key = f"{_CACHE_ROOT}/{_VERSION_FOLDER}/{tbl_name}.pqt"
            s3_path = f"s3://{self.bucket}/{s3_key}"
            parquet_paths.append(f"'{s3_path}'")
            asset_names.append(tbl_name)

        try:
            union_query = " UNION ALL ".join(
                [
                    f"SELECT *, '{asset}' as asset_name FROM read_parquet({path})"
                    for path, asset in zip(parquet_paths, asset_names, strict=False)
                ]
            )
            result = duckdb.query(union_query).to_df()
            logging.info(
                CacheLogMessage(
                    backend="S3Backend", table="merged", message=f"Merged {len(table_names)} tables from S3"
                ).to_json()
            )
            return result
        except Exception as e:
            logging.warning(
                CacheLogMessage(backend="S3Backend", table="merged", message=f"Error merging tables: {e}").to_json()
            )
            return pd.DataFrame()


class MemoryBackend(Backend):
    """A simple in-memory backend for testing or local development."""

    def __init__(self) -> None:
        """Initialize MemoryBackend with empty store."""
        super().__init__()
        self._store: dict[str, pd.DataFrame] = {}
        self._json_store: dict[str, str] = {}

    def write(self, table_name: str, data: pd.DataFrame) -> None:
        """Store DataFrame in memory."""
        logging.info(
            CacheLogMessage(
                backend="MemoryBackend", table=table_name, message=f"Storing cache in memory for {table_name}"
            ).to_json()
        )
        self._store[table_name] = data

    def read(self, table_name: str | list[str]) -> pd.DataFrame:
        """Fetch DataFrame from memory.

        When given a list of table names, merges them and adds
        an 'asset_name' column.
        """
        if isinstance(table_name, list):
            return self._read_multiple(table_name)
        return self._read_single(table_name)

    def _read_single(self, table_name: str) -> pd.DataFrame:
        """Fetch a single table from memory."""
        logging.info(
            CacheLogMessage(
                backend="MemoryBackend", table=table_name, message=f"Fetching cache from memory for {table_name}"
            ).to_json()
        )
        return self._store.get(table_name, pd.DataFrame())

    def get_location(self, table_name: str, partitioned: bool = False) -> str:
        """Return the in-memory identifier for a given table."""
        if partitioned:
            return f"{_VERSION_FOLDER}/{table_name}/"
        if "/" in table_name:
            base, value = table_name.split("/", 1)
            partition_key = HIVE_PARTITION_KEYS[base]
            return f"{_VERSION_FOLDER}/{base}/{partition_key}={value}/data.pqt"
        return f"{_VERSION_FOLDER}/{table_name}.pqt"

    def put_json(self, key: str, data: str) -> None:
        """Store a JSON string in the versioned in-memory JSON store and update index."""
        logging.info(
            CacheLogMessage(
                backend="MemoryBackend", table=key, message=f"Storing metadata in memory for {key}"
            ).to_json()
        )
        self._json_store[f"{_VERSION_FOLDER}/{key}"] = data
        existing = json.loads(self._json_store.get("cache_versions.json", "[]"))
        if _VERSION_FOLDER not in existing:
            existing.append(_VERSION_FOLDER)
        self._json_store["cache_versions.json"] = json.dumps(existing)

    def get_json(self, key: str) -> str:
        """Read a JSON string from the versioned in-memory JSON store."""
        return self._json_store.get(f"{_VERSION_FOLDER}/{key}", "{}")

    def get_versions_index(self) -> list[str]:
        """Return the list of all available version folders from the in-memory index."""
        return json.loads(self._json_store.get("cache_versions.json", "[]"))

    def _read_multiple(self, table_names: list[str]) -> pd.DataFrame:
        """Fetch and merge multiple tables from memory."""
        dfs = []
        for tbl_name in table_names:
            df = self._store.get(tbl_name, pd.DataFrame())
            if not df.empty:
                df = df.copy()
                df["asset_name"] = tbl_name
                dfs.append(df)

        if not dfs:
            logging.warning(
                CacheLogMessage(
                    backend="MemoryBackend", table="merged", message=f"No valid tables found among {table_names}"
                ).to_json()
            )
            return pd.DataFrame()

        result = pd.concat(dfs, ignore_index=True)
        logging.info(
            CacheLogMessage(
                backend="MemoryBackend", table="merged", message=f"Merged {len(dfs)} tables from memory"
            ).to_json()
        )
        return result
