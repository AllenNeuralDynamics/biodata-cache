"""Utility functions for zombie-squirrel package."""

import logging
import re
from typing import Optional

from pydantic import BaseModel


class SquirrelMessage(BaseModel):
    """Structured logging message for zombie-squirrel operations."""

    tree: str
    acorn: str
    message: str

    def to_json(self) -> str:
        """Convert message to JSON string."""
        return self.model_dump_json()


def setup_logging():
    """Configure logging for zombie-squirrel package.

    Sets up INFO level logging with timestamp format.
    Safe to call multiple times - uses force=True to reconfigure.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True)


def prefix_table_name(table_name: str) -> str:
    """Add zombie-squirrel prefix and parquet extension to filenames.

    Args:
        table_name: The base table name.

    Returns:
        Filename with 'zs_' prefix and '.pqt' extension.

    """
    return "zs_" + table_name + ".pqt"


def get_s3_cache_path(filename: str) -> str:
    """Get the full S3 path for a cache file.

    Args:
        filename: The cache filename (e.g., "zs_unique_project_names.pqt").

    Returns:
        Full S3 path: data-asset-cache/filename

    """
    return f"data-asset-cache/{filename}"


def get_squirrel_info():
    """Fetch and return the Squirrel metadata from the active tree."""
    import zombie_squirrel.acorns as acorns
    from zombie_squirrel.squirrel import Squirrel

    data = acorns.TREE.fetch("squirrel.json")
    return Squirrel.model_validate_json(data)


_INSTRUMENT_ID_RE = re.compile(
    r'^[^_-]+[_-](.+)_(\d{8}|\d{4}-\d{2}-\d{2}|2[3-6]\d{4})$'
)


def normalize_instrument_id(instrument_id: Optional[str]) -> str:
    if not instrument_id:
        return ""
    s = str(instrument_id)
    m = _INSTRUMENT_ID_RE.match(s)
    name = m.group(1) if m else s
    return re.sub(r"[_-]", "", name)


def normalize_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9 ]", " ", str(name))
    s = re.sub(r"\s+", " ", s).strip()
    return s.title()


def _merge_key(display_name: str) -> str:
    return display_name.lower().replace(" ", "")


def parse_experimenters(val: Optional[str]) -> list:
    if not val:
        return []
    seen: set = set()
    result = []
    for part in str(val).split(","):
        normalized = normalize_name(part)
        if not normalized:
            continue
        key = _merge_key(normalized)
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def normalize_experimenters(names: list) -> list:
    seen: set = set()
    result = []
    for val in names:
        for normalized in parse_experimenters(val):
            key = _merge_key(normalized)
            if key not in seen:
                seen.add(key)
                result.append(normalized)
    return sorted(result)
