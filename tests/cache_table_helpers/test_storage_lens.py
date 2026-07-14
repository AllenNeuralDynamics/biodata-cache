"""Unit tests for storage_lens cache table."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from biodata_cache.cache_table_helpers.storage_lens import (
    _fetch_storage_lens,
    _get_ssl_cert,
    storage_lens,
    storage_lens_columns,
)

_SAMPLE_DF = pd.DataFrame(
    {
        "prefix": ["abc123"],
        "bucket": ["my-bucket"],
        "subprefix": ["abc123/file.json"],
        "storage_class": ["STANDARD"],
        "intelligent_tiering_access_tier": [None],
        "size_in_bytes": [1024],
        "number_of_files": [1],
        "project_name": ["proj1"],
        "report_date": ["2026-06-28T01-00Z"],
    }
)


@patch("biodata_cache.cache_table_helpers.storage_lens.registry.BACKEND")
def test_cache_hit(mock_backend):
    mock_backend.read.return_value = _SAMPLE_DF.copy()
    result = storage_lens(force_update=False)
    assert len(result) == 1
    assert result.iloc[0]["bucket"] == "my-bucket"


@patch("biodata_cache.cache_table_helpers.storage_lens.registry.BACKEND")
def test_empty_cache_raises_error(mock_backend):
    mock_backend.read.return_value = pd.DataFrame()
    with pytest.raises(ValueError, match="Cache is empty"):
        storage_lens(force_update=False)


@patch("biodata_cache.cache_table_helpers.storage_lens._fetch_storage_lens")
@patch("biodata_cache.cache_table_helpers.storage_lens.registry.BACKEND")
def test_force_update_fetches_and_writes(mock_backend, mock_fetch):
    mock_backend.read.return_value = _SAMPLE_DF.copy()
    mock_fetch.return_value = _SAMPLE_DF.copy()
    storage_lens(force_update=True)
    mock_fetch.assert_called_once()
    mock_backend.write.assert_called_once()


@patch("biodata_cache.cache_table_helpers.storage_lens._fetch_storage_lens")
@patch("biodata_cache.cache_table_helpers.storage_lens.registry.BACKEND")
def test_cache_miss_fetches_and_writes(mock_backend, mock_fetch):
    mock_backend.read.return_value = pd.DataFrame()
    mock_fetch.return_value = _SAMPLE_DF.copy()
    result = storage_lens(force_update=True)
    mock_fetch.assert_called_once()
    mock_backend.write.assert_called_once_with("storage_lens", mock_fetch.return_value)
    assert len(result) == 1


def test_storage_lens_columns():
    cols = storage_lens_columns()
    names = [c.name for c in cols]
    assert names == [
        "prefix",
        "bucket",
        "subprefix",
        "storage_class",
        "intelligent_tiering_access_tier",
        "size_in_bytes",
        "number_of_files",
        "project_name",
        "report_date",
    ]


@patch("biodata_cache.cache_table_helpers.storage_lens.os.path.exists")
def test_get_ssl_cert_uses_bundled_cert(mock_exists):
    mock_exists.return_value = False
    mock_files = MagicMock()
    mock_files.return_value.joinpath.return_value.read_bytes.return_value = b"cert-data"
    with patch("biodata_cache.cache_table_helpers.storage_lens.files", mock_files), \
         patch("builtins.open", MagicMock()):
        _get_ssl_cert()
    mock_files.return_value.joinpath.assert_called_once_with("global-bundle.pem")


@patch("biodata_cache.cache_table_helpers.storage_lens.os.path.exists")
def test_get_ssl_cert_downloads_if_missing(mock_exists):
    mock_exists.return_value = False
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"cert-data"
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_files = MagicMock()
    mock_files.return_value.joinpath.return_value.read_bytes.side_effect = FileNotFoundError
    with patch("biodata_cache.cache_table_helpers.storage_lens.files", mock_files), \
         patch("biodata_cache.cache_table_helpers.storage_lens.urllib.request.urlopen", return_value=mock_resp), \
         patch("builtins.open", MagicMock()):
        _get_ssl_cert()


@patch("biodata_cache.cache_table_helpers.storage_lens.os.path.exists")
def test_get_ssl_cert_skips_download_if_present(mock_exists):
    mock_exists.return_value = True
    mock_files = MagicMock()
    mock_files.return_value.joinpath.return_value.read_bytes.return_value = b"cert-data"
    with patch("biodata_cache.cache_table_helpers.storage_lens.files", mock_files), \
         patch("biodata_cache.cache_table_helpers.storage_lens.urllib.request.urlopen") as mock_urlopen, \
         patch("builtins.open", MagicMock()):
        _get_ssl_cert()
        mock_urlopen.assert_not_called()


@patch("biodata_cache.cache_table_helpers.storage_lens._get_ssl_cert")
@patch("aind_data_access_api.secrets.get_secret")
def test_fetch_storage_lens_calls_rds(mock_get_secret, mock_cert):
    mock_get_secret.return_value = {
        "username": "user",
        "password": "pass",
        "host": "db.example.com",
        "port": 5432,
        "dbname": "storage_lens_metrics",
        "engine": "postgres",
        "masterarn": "arn:aws:secretsmanager:us-west-2:123456789:secret:test",
    }
    mock_cert.return_value = "/tmp/global-bundle.pem"

    mock_conn = MagicMock()
    mock_eng = MagicMock()
    mock_eng.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_eng.connect.return_value.__exit__ = MagicMock(return_value=False)

    with patch("sqlalchemy.create_engine", return_value=mock_eng), patch(
        "pandas.read_sql_query", return_value=iter([_SAMPLE_DF.copy()])
    ):
        result = _fetch_storage_lens()

    assert len(result) == 1
    mock_get_secret.assert_called_once()
