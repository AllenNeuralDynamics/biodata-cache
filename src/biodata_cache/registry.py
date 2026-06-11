"""Cache table registry: functions to fetch and cache data from MongoDB."""

import logging
import os
from collections.abc import Callable
from typing import Any

from biodata_cache.backend import (
    MemoryBackend,
    S3Backend,
)
from biodata_cache.utils import CacheLogMessage

# --- Backend setup ---------------------------------------------------

API_GATEWAY_HOST = "api.allenneuraldynamics.org"

backend_type = os.getenv("BIODATA_CACHE_BACKEND", "memory").lower()

if backend_type == "s3":  # pragma: no cover
    logging.info(
        CacheLogMessage(backend="S3Backend", table="system", message="Initializing S3 backend for caching").to_json()
    )
    BACKEND = S3Backend()
elif backend_type == "memory":  # pragma: no cover
    logging.info(
        CacheLogMessage(
            backend="MemoryBackend", table="system", message="Initializing in-memory backend for caching"
        ).to_json()
    )
    BACKEND = MemoryBackend()
else:  # pragma: no cover
    raise ValueError(f"Unknown BIODATA_CACHE_BACKEND: {backend_type}")

# --- Cache table registry and names -------------------------------------------

NAMES = {
    "upn": "unique_project_names",
    "usi": "unique_subject_ids",
    "ugt": "unique_genotypes",
    "basics": "asset_basics",
    "d2r": "source_data",
    "r2d": "raw_to_derived",
    "qc": "quality_control",
    "smartspim": "assets_smartspim",
    "exaspim": "platform_exaspim",
    "upgrade": "metadata_upgrade",
    "fib": "platform_fib",
    "core": "metadata_core",
    "foraging": "foraging_sessions",
    "curriculum": "behavior_curriculum",
    "platform_qc": "platform_qc",
}

TABLE_REGISTRY: dict[str, Callable[[], Any]] = {}


def register_table(name: str):
    """Register cache table function with registry."""

    def decorator(func):
        """Register function in cache table registry."""
        TABLE_REGISTRY[name] = func
        return func

    return decorator
