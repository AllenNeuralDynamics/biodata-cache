"""Unit tests for unique_genotypes cache table."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.unique_genotypes import (
    unique_genotypes,
    unique_genotypes_columns,
)


@patch("biodata_cache.cache_table_helpers.unique_genotypes.registry.BACKEND")
def test_unique_genotypes_empty_cache_raises(mock_backend):
    mock_backend.read.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        unique_genotypes(force_update=False)


@patch("biodata_cache.cache_table_helpers.unique_genotypes.registry.BACKEND")
def test_unique_genotypes_cache_hit(mock_backend):
    mock_backend.read.return_value = pd.DataFrame({"genotype": ["Ai32", "Ai148"]})
    result = unique_genotypes(force_update=False)
    assert result == ["Ai32", "Ai148"]


@patch("biodata_cache.cache_table_helpers.unique_genotypes.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.unique_genotypes.registry.BACKEND")
def test_unique_genotypes_force_update(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.aggregate_docdb_records.return_value = [
        {"genotype": "Ai32"},
        {"genotype": "Vip-IRES-Cre"},
    ]
    result = unique_genotypes(force_update=True)
    assert "Ai32" in result
    assert "Vip-IRES-Cre" in result
    mock_backend.write.assert_called_once()


@patch("biodata_cache.cache_table_helpers.unique_genotypes.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.unique_genotypes.registry.BACKEND")
def test_unique_genotypes_excludes_null(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.aggregate_docdb_records.return_value = [
        {"genotype": "Ai32"},
        {"genotype": None},
    ]
    result = unique_genotypes(force_update=True)
    assert None not in result
    assert "Ai32" in result


@patch("biodata_cache.cache_table_helpers.unique_genotypes.MetadataDbClient")
@patch("biodata_cache.cache_table_helpers.unique_genotypes.registry.BACKEND")
def test_unique_genotypes_pipeline_filters_nulls(mock_backend, mock_client_class):
    mock_backend.read.return_value = pd.DataFrame()
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.aggregate_docdb_records.return_value = [{"genotype": "Ai32"}]
    unique_genotypes(force_update=True)
    pipeline = mock_client.aggregate_docdb_records.call_args[1]["pipeline"]
    match_stage = pipeline[0]["$match"]
    assert "subject.subject_details.genotype" in match_stage


def test_unique_genotypes_columns_names():
    cols = unique_genotypes_columns()
    assert len(cols) == 1
    assert cols[0].name == "genotype"
