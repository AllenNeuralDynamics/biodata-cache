"""
normalization.py — Back-end equivalents of the JS normalisation helpers in
web/src/lib/utils.js.

Instrument-ID normalisation
----------------------------
Pattern (from INSTRUMENT_ID_REGEX):
    ^<location>[_-]<name>_<date>$

where <date> is one of:
    YYYYMMDD          — 8 digits
    YYYY-MM-DD        — ISO date
    YYMMDD            — short year 23–26 (i.e. starts with 2[3-6])

The <name> group is extracted, then all remaining '-' and '_' characters are
stripped.  IDs that do not match the pattern are returned unchanged (spacers
still stripped).

Experimenter-name normalisation
--------------------------------
Raw experimenter fields are comma-separated strings of AIND usernames, e.g.
``"nick.ponvert, anna.katelyn.mcdougal"``.  Each part is normalised to a
title-cased display name; duplicates (by case-insensitive merged key) are
removed.
"""

import re
from typing import Optional

# Mirror of INSTRUMENT_ID_REGEX in web/src/lib/utils.js.
# Group 1 captures the <name> segment.
_INSTRUMENT_ID_RE = re.compile(
    r'^[^_-]+[_-](.+)_(\d{8}|\d{4}-\d{2}-\d{2}|2[3-6]\d{4})$'
)


def normalize_instrument_id(instrument_id: Optional[str]) -> str:
    """
    Normalize a raw instrument_id to its canonical short name.

    Examples
    --------
    >>> normalize_instrument_id("AIND_MESO2_20240115")
    'MESO2'
    >>> normalize_instrument_id("HQ_NP3_20231005")
    'NP3'
    >>> normalize_instrument_id("HQ-NP3_20231005")
    'NP3'
    >>> normalize_instrument_id("MESO2")   # already short — returned as-is
    'MESO2'
    >>> normalize_instrument_id(None)
    ''
    """
    if not instrument_id:
        return ""
    s = str(instrument_id)
    m = _INSTRUMENT_ID_RE.match(s)
    name = m.group(1) if m else s
    return re.sub(r"[_-]", "", name)


# ---------------------------------------------------------------------------
# Experimenter-name normalisation
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """
    Normalize a single experimenter name to a title-cased display name.

    Mirrors ``normalizeName()`` in web/src/lib/utils.js:
    - Replace all non-alphanumeric, non-space characters with a space
      (converts dots, underscores, hyphens, etc.)
    - Collapse runs of whitespace to a single space and strip
    - Title-case the result

    >>> normalize_name("anna.katelyn.mcdougal")
    'Anna Katelyn Mcdougal'
    >>> normalize_name("nick.ponvert")
    'Nick Ponvert'
    >>> normalize_name("  john  doe  ")
    'John Doe'
    >>> normalize_name("john_doe")
    'John Doe'
    >>> normalize_name("")
    ''
    """
    s = re.sub(r"[^a-zA-Z0-9 ]", " ", str(name))
    s = re.sub(r"\s+", " ", s).strip()
    return s.title()


def _merge_key(display_name: str) -> str:
    """
    Deduplication key: lowercase with spaces removed.

    "John Doe" and "JohnDoe" both produce "johndoe".

    >>> _merge_key("John Doe")
    'johndoe'
    >>> _merge_key("Anna Katelyn Mcdougal")
    'annakatelynmcdougal'
    """
    return display_name.lower().replace(" ", "")


def parse_experimenters(val: Optional[str]) -> list:
    """
    Parse a comma-separated experimenter field into a deduplicated list of
    normalized display names.

    Mirrors ``parseExperimenters()`` in web/src/lib/utils.js.

    >>> parse_experimenters("nick.ponvert, anna.katelyn.mcdougal")
    ['Nick Ponvert', 'Anna Katelyn Mcdougal']
    >>> parse_experimenters("john.doe, John Doe")
    ['John Doe']
    >>> parse_experimenters(None)
    []
    >>> parse_experimenters("")
    []
    """
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
    """
    Normalize a list of raw experimenter name strings, where each element may
    itself be a comma-separated field (e.g. as stored in the ``experimenters``
    column of asset_basics).

    Returns a deduplicated, sorted list of normalized display names.

    Mirrors ``uniqueExperimenters()`` in web/src/lib/utils.js.

    >>> normalize_experimenters(["nick.ponvert", "anna.katelyn.mcdougal"])
    ['Anna Katelyn Mcdougal', 'Nick Ponvert']
    >>> normalize_experimenters(["nick.ponvert, anna.katelyn.mcdougal"])
    ['Anna Katelyn Mcdougal', 'Nick Ponvert']
    >>> normalize_experimenters(["john.doe", "John Doe", "john.doe"])
    ['John Doe']
    >>> normalize_experimenters([])
    []
    >>> normalize_experimenters([None, "", "nick.ponvert"])
    ['Nick Ponvert']
    """
    seen: set = set()
    result = []
    for val in names:
        for normalized in parse_experimenters(val):
            key = _merge_key(normalized)
            if key not in seen:
                seen.add(key)
                result.append(normalized)
    return sorted(result)
