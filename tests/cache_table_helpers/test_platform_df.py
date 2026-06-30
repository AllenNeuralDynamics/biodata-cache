"""Unit tests for platform_df cache tables."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import biodata_cache.cache_table_helpers.platform_df as platform_df
from biodata_cache.cache_table_helpers.platform_df import (
    platform_dynamic_foraging_events,
    platform_dynamic_foraging_events_columns,
    platform_dynamic_foraging_sessions,
    platform_dynamic_foraging_sessions_columns,
    platform_dynamic_foraging_trials,
    platform_dynamic_foraging_trials_columns,
)
from biodata_cache.registry import NAMES


def _sessions_df():
    return pd.DataFrame(
        {
            "_session_id": ["sub1_2024-01-01_1"],
            "subject_id": ["sub1"],
            "session_date": ["2024-01-01"],
            "task": ["Coupled Baiting"],
        }
    )


def _trials_df():
    return pd.DataFrame(
        {
            "session_id": ["sub1_2024-01-01_1"],
            "subject_id": ["sub1"],
            "trial": [0],
            "animal_response": [1.0],
        }
    )


def _events_df():
    return pd.DataFrame(
        {
            "session_id": ["sub1_2024-01-01_1"],
            "subject_id": ["sub1"],
            "trial": [0],
            "timestamps": [0.5],
            "event": ["left_lick_time"],
        }
    )


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_session_table")
def test_sessions_reads_from_cache_when_present(mock_read, mock_registry):
    mock_registry.NAMES = {"df_sessions": "platform_dynamic_foraging_sessions"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = _sessions_df()

    result = platform_dynamic_foraging_sessions()

    mock_read.assert_not_called()
    mock_registry.BACKEND.write.assert_not_called()
    assert list(result.columns) == ["_session_id", "subject_id", "session_date", "task"]


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_session_table")
def test_sessions_raises_on_empty_cache_without_force(mock_read, mock_registry):
    mock_registry.NAMES = {"df_sessions": "platform_dynamic_foraging_sessions"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()

    with pytest.raises(ValueError, match="Cache is empty"):
        platform_dynamic_foraging_sessions()
    mock_read.assert_not_called()


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_session_table")
def test_sessions_force_update_fetches_and_writes(mock_read, mock_registry):
    mock_registry.NAMES = {"df_sessions": "platform_dynamic_foraging_sessions"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = _sessions_df()
    mock_read.return_value = _sessions_df()

    platform_dynamic_foraging_sessions(force_update=True)

    mock_read.assert_called_once()
    mock_registry.BACKEND.write.assert_called_once()
    args = mock_registry.BACKEND.write.call_args[0]
    assert args[0] == "platform_dynamic_foraging_sessions"


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_session_table")
def test_sessions_empty_cache_with_force_fetches(mock_read, mock_registry):
    mock_registry.NAMES = {"df_sessions": "platform_dynamic_foraging_sessions"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    mock_read.return_value = _sessions_df()

    result = platform_dynamic_foraging_sessions(force_update=True)

    mock_read.assert_called_once()
    mock_registry.BACKEND.write.assert_called_once()
    assert not result.empty


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_trials_uses_subject_partition_cache_key(mock_read, mock_registry):
    mock_registry.NAMES = {"df_trials": "platform_dynamic_foraging_trials"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = _trials_df()

    platform_dynamic_foraging_trials(subject_id="sub1")

    mock_registry.BACKEND.read.assert_called_once_with("platform_dynamic_foraging_trials/sub1")
    mock_read.assert_not_called()


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_trials_raises_on_empty_cache_without_force(mock_read, mock_registry):
    mock_registry.NAMES = {"df_trials": "platform_dynamic_foraging_trials"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()

    with pytest.raises(ValueError, match="Cache is empty for subject sub1"):
        platform_dynamic_foraging_trials(subject_id="sub1")
    mock_read.assert_not_called()


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_trials_force_update_writes_to_subject_partition(mock_read, mock_registry):
    mock_registry.NAMES = {"df_trials": "platform_dynamic_foraging_trials"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = _trials_df()
    mock_read.return_value = _trials_df()

    platform_dynamic_foraging_trials(subject_id="sub1", force_update=True)

    mock_read.assert_called_once()
    base_arg = mock_read.call_args[0][0]
    subject_arg = mock_read.call_args[0][1]
    assert "trial_table" in base_arg or base_arg.endswith("trial_table")
    assert subject_arg == "sub1"
    mock_registry.BACKEND.write.assert_called_once()
    write_key = mock_registry.BACKEND.write.call_args[0][0]
    assert write_key == "platform_dynamic_foraging_trials/sub1"


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_trials_subject_id_is_stringified(mock_read, mock_registry):
    mock_registry.NAMES = {"df_trials": "platform_dynamic_foraging_trials"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    mock_read.return_value = _trials_df()

    platform_dynamic_foraging_trials(subject_id=754372, force_update=True)

    assert mock_read.call_args[0][1] == "754372"


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_trials_skips_write_when_partition_missing(mock_read, mock_registry):
    mock_registry.NAMES = {"df_trials": "platform_dynamic_foraging_trials"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    mock_read.return_value = pd.DataFrame()

    result = platform_dynamic_foraging_trials(subject_id="sub1", force_update=True)

    mock_read.assert_called_once()
    mock_registry.BACKEND.write.assert_not_called()
    assert result.empty


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_events_uses_subject_partition_cache_key(mock_read, mock_registry):
    mock_registry.NAMES = {"df_events": "platform_dynamic_foraging_events"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = _events_df()

    platform_dynamic_foraging_events(subject_id="sub1")

    mock_registry.BACKEND.read.assert_called_once_with("platform_dynamic_foraging_events/sub1")
    mock_read.assert_not_called()


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_events_raises_on_empty_cache_without_force(mock_read, mock_registry):
    mock_registry.NAMES = {"df_events": "platform_dynamic_foraging_events"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()

    with pytest.raises(ValueError, match="Cache is empty for subject sub1"):
        platform_dynamic_foraging_events(subject_id="sub1")
    mock_read.assert_not_called()


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_events_force_update_writes_to_subject_partition(mock_read, mock_registry):
    mock_registry.NAMES = {"df_events": "platform_dynamic_foraging_events"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = _events_df()
    mock_read.return_value = _events_df()

    platform_dynamic_foraging_events(subject_id="sub1", force_update=True)

    mock_read.assert_called_once()
    base_arg = mock_read.call_args[0][0]
    assert "event_table" in base_arg or base_arg.endswith("event_table")
    mock_registry.BACKEND.write.assert_called_once()
    write_key = mock_registry.BACKEND.write.call_args[0][0]
    assert write_key == "platform_dynamic_foraging_events/sub1"


@patch("biodata_cache.cache_table_helpers.platform_df.registry")
@patch("biodata_cache.cache_table_helpers.platform_df._read_subject_partition")
def test_events_skips_write_when_partition_missing(mock_read, mock_registry):
    mock_registry.NAMES = {"df_events": "platform_dynamic_foraging_events"}
    mock_registry.BACKEND = MagicMock()
    mock_registry.BACKEND.__class__.__name__ = "MemoryBackend"
    mock_registry.BACKEND.read.return_value = pd.DataFrame()
    mock_read.return_value = pd.DataFrame()

    result = platform_dynamic_foraging_events(subject_id="sub1", force_update=True)

    mock_read.assert_called_once()
    mock_registry.BACKEND.write.assert_not_called()
    assert result.empty


def test_read_subject_partition_returns_empty_on_missing_files():
    con = MagicMock()
    con.sql.side_effect = platform_df.duckdb.IOException("No files found that match the pattern")
    cm = MagicMock()
    cm.__enter__.return_value = con
    with patch.object(platform_df.duckdb, "connect", return_value=cm):
        result = platform_df._read_subject_partition("s3://bucket/trial_table", "sub1")

    assert result.empty


def test_read_subject_partition_reraises_other_io_errors():
    con = MagicMock()
    con.sql.side_effect = platform_df.duckdb.IOException("Access Denied")
    cm = MagicMock()
    cm.__enter__.return_value = con
    with patch.object(platform_df.duckdb, "connect", return_value=cm):
        with pytest.raises(platform_df.duckdb.IOException, match="Access Denied"):
            platform_df._read_subject_partition("s3://bucket/trial_table", "sub1")


def test_columns_lists_are_nonempty_and_have_keys():
    sess = platform_dynamic_foraging_sessions_columns()
    trials = platform_dynamic_foraging_trials_columns()
    events = platform_dynamic_foraging_events_columns()
    assert len(sess) > 0
    assert len(trials) > 0
    assert len(events) > 0
    sess_names = {c.name for c in sess}
    trial_names = {c.name for c in trials}
    event_names = {c.name for c in events}
    assert {"_session_id", "subject_id", "session_date"}.issubset(sess_names)
    assert {"session_id", "subject_id", "trial"}.issubset(trial_names)
    assert {"session_id", "subject_id", "timestamps", "event"}.issubset(event_names)


def test_events_columns_are_all_ten():
    cols = platform_dynamic_foraging_events_columns()
    assert len(cols) == 10


def test_registry_names_present():
    assert NAMES["df_sessions"] == "platform_dynamic_foraging_sessions"
    assert NAMES["df_trials"] == "platform_dynamic_foraging_trials"
    assert NAMES["df_events"] == "platform_dynamic_foraging_events"

