"""Unit tests for platform_mouselight cache table."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.platform_mouselight import (
    platform_mouselight,
    platform_mouselight_columns,
)


def _graphql_response():
    return {
        "data": {
            "searchNeurons": {
                "totalCount": 2,
                "neurons": [
                    {
                        "id": "uuid-b",
                        "idString": "AA0002",
                        "brainArea": {"acronym": "MOp"},
                        "tracings": [
                            {"id": "tr-b1", "tracingStructure": {"name": "axon", "value": 1}},
                        ],
                    },
                    {
                        "id": "uuid-a",
                        "idString": "AA0001",
                        "brainArea": {"acronym": "VISp"},
                        "tracings": [
                            {"id": "tr-a1", "tracingStructure": {"name": "axon", "value": 1}},
                            {"id": "tr-a2", "tracingStructure": {"name": "dendrite", "value": 2}},
                        ],
                    },
                ],
                "error": None,
            }
        }
    }


@patch("biodata_cache.cache_table_helpers.platform_mouselight.registry.BACKEND")
def test_cache_hit(mock_backend):
    cached = pd.DataFrame(
        {
            "id": ["uuid-a"],
            "id_string": ["AA0001"],
            "region": ["VISp"],
            "tracings": ['[{"id": "tr-a1", "kind": "axon"}]'],
        }
    )
    mock_backend.read.return_value = cached
    result = platform_mouselight(force_update=False)
    assert list(result["id_string"]) == ["AA0001"]
    mock_backend.write.assert_not_called()


@patch("biodata_cache.cache_table_helpers.platform_mouselight.registry.BACKEND")
def test_empty_cache_raises_error(mock_backend):
    mock_backend.read.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        platform_mouselight(force_update=False)


@patch("biodata_cache.cache_table_helpers.platform_mouselight.urllib.request.urlopen")
@patch("biodata_cache.cache_table_helpers.platform_mouselight.registry.BACKEND")
def test_cache_miss_fetches_and_sorts(mock_backend, mock_urlopen):
    mock_backend.read.return_value = pd.DataFrame()
    resp = MagicMock()
    resp.read.return_value = json.dumps(_graphql_response()).encode()
    mock_urlopen.return_value.__enter__.return_value = resp

    result = platform_mouselight(force_update=True)

    # Sorted by id_string ascending.
    assert list(result["id_string"]) == ["AA0001", "AA0002"]
    assert list(result["region"]) == ["VISp", "MOp"]
    # tracings stored as JSON string with id + kind.
    first = json.loads(result.iloc[0]["tracings"])
    assert first == [
        {"id": "tr-a1", "kind": "axon"},
        {"id": "tr-a2", "kind": "dendrite"},
    ]
    mock_backend.write.assert_called_once()


@patch("biodata_cache.cache_table_helpers.platform_mouselight.urllib.request.urlopen")
@patch("biodata_cache.cache_table_helpers.platform_mouselight.registry.BACKEND")
def test_graphql_error_raises(mock_backend, mock_urlopen):
    mock_backend.read.return_value = pd.DataFrame()
    resp = MagicMock()
    resp.read.return_value = json.dumps({"errors": [{"message": "boom"}]}).encode()
    mock_urlopen.return_value.__enter__.return_value = resp
    with pytest.raises(ValueError, match="boom"):
        platform_mouselight(force_update=True)


def test_columns():
    cols = platform_mouselight_columns()
    assert [c.name for c in cols] == ["id", "id_string", "region", "tracings"]
