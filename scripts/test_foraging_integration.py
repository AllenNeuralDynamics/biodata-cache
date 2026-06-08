"""Integration tests for the foraging acorn against the upstream public S3 tables.

Run with FOREST_TYPE=memory (default). These tests read from the public upstream
S3 cache — no AWS credentials required. They compare row values against known
sessions to catch schema or data drift between zombie-squirrel and the upstream build.

Usage:
    cd /path/to/zombie-squirrel
    python -m pytest scripts/test_foraging_integration.py -v
"""

import math

import duckdb
import pandas as pd
import pytest

from zombie_squirrel.acorn_helpers.foraging.query import (
    SESSION_DB,
    TRIAL_DB,
    fetch_trials,
    select_sessions,
)
from zombie_squirrel.acorn_helpers.foraging.session import (
    UPSTREAM_SESSION_S3,
    _add_asset_name,
    _fetch_upstream,
)

# A known stable session from 2024 (unlikely to be modified retroactively).
# Values verified against the upstream parquet on 2026-06-08.
_KNOWN_SUBJECT = "699982"
_KNOWN_DATE = "2024-01-09"


@pytest.fixture(scope="module")
def upstream_session_sample():
    """Fetch a small slice of the upstream session table for comparison."""
    conn = duckdb.connect()
    conn.execute("INSTALL httpfs; LOAD httpfs;")
    return conn.sql(
        f"SELECT * FROM read_parquet('{UPSTREAM_SESSION_S3}') "
        f"WHERE subject_id = '{_KNOWN_SUBJECT}' AND session_date = '{_KNOWN_DATE}'"
    ).df()


class TestUpstreamSessionTableStructure:
    def test_upstream_has_expected_columns(self, upstream_session_sample):
        expected = {
            "subject_id", "session_date", "nwb_suffix", "_session_id",
            "co_asset_id", "co_s3_nwb_uri", "nwb_data_source",
            "foraging_eff", "finished_trials", "bias_naive",
            "curriculum_name", "current_stage_actual",
        }
        assert expected.issubset(set(upstream_session_sample.columns))

    def test_known_session_exists(self, upstream_session_sample):
        assert len(upstream_session_sample) >= 1, (
            f"Expected at least one session for subject {_KNOWN_SUBJECT} on {_KNOWN_DATE}"
        )

    def test_known_session_subject_id(self, upstream_session_sample):
        assert upstream_session_sample["subject_id"].iloc[0] == _KNOWN_SUBJECT

    def test_known_session_date(self, upstream_session_sample):
        assert upstream_session_sample["session_date"].iloc[0] == _KNOWN_DATE

    def test_known_session_has_session_id(self, upstream_session_sample):
        sid = upstream_session_sample["_session_id"].iloc[0]
        assert sid.startswith(f"{_KNOWN_SUBJECT}_{_KNOWN_DATE}_")


class TestAddAssetNameOnUpstream:
    def test_asset_name_derived_from_co_uri(self, upstream_session_sample):
        enriched = _add_asset_name(upstream_session_sample)
        row = enriched.iloc[0]
        if pd.notna(row["co_s3_nwb_uri"]):
            assert pd.notna(row["asset_name"])
            assert row["asset_name"].startswith("behavior_")
            assert _KNOWN_SUBJECT in row["asset_name"]
        else:
            pytest.skip("Known session has no CO asset URI; skipping asset_name check")

    def test_asset_name_matches_co_uri_stem(self, upstream_session_sample):
        enriched = _add_asset_name(upstream_session_sample)
        for _, row in enriched.iterrows():
            if pd.notna(row["co_s3_nwb_uri"]):
                expected = row["co_s3_nwb_uri"].rsplit("/", 1)[-1].replace(".nwb", "")
                assert row["asset_name"] == expected


class TestSelectSessions:
    def test_returns_dataframe(self):
        result = select_sessions(subjects=[_KNOWN_SUBJECT])
        assert isinstance(result, pd.DataFrame)

    def test_subject_filter(self):
        result = select_sessions(subjects=[_KNOWN_SUBJECT])
        assert (result["subject_id"] == _KNOWN_SUBJECT).all()

    def test_where_clause_filters(self):
        result = select_sessions(
            subjects=[_KNOWN_SUBJECT],
            where="session_date IS NOT NULL",
        )
        assert len(result) > 0

    def test_extra_columns_carried(self):
        result = select_sessions(
            subjects=[_KNOWN_SUBJECT],
            columns=["foraging_eff", "finished_trials"],
        )
        assert "foraging_eff" in result.columns
        assert "finished_trials" in result.columns
        assert "_session_id" in result.columns

    def test_empty_result_for_nonexistent_subject(self):
        result = select_sessions(subjects=["000000_nonexistent"])
        assert len(result) == 0

    def test_values_match_upstream(self, upstream_session_sample):
        result = select_sessions(
            subjects=[_KNOWN_SUBJECT],
            columns=["foraging_eff", "bias_naive", "finished_trials"],
            where=f"session_date = '{_KNOWN_DATE}'",
        )
        assert len(result) >= 1
        our_row = result.iloc[0]
        up_row = upstream_session_sample.iloc[0]

        if pd.notna(up_row["foraging_eff"]) and pd.notna(our_row["foraging_eff"]):
            assert math.isclose(our_row["foraging_eff"], up_row["foraging_eff"], rel_tol=1e-6)
        if pd.notna(up_row["finished_trials"]) and pd.notna(our_row["finished_trials"]):
            assert our_row["finished_trials"] == up_row["finished_trials"]


class TestFetchTrials:
    def test_returns_dataframe(self):
        sessions = select_sessions(subjects=[_KNOWN_SUBJECT], where=f"session_date = '{_KNOWN_DATE}'")
        if len(sessions) == 0:
            pytest.skip("No sessions found for known subject/date")
        trials = fetch_trials(sessions)
        assert isinstance(trials, pd.DataFrame)

    def test_has_required_columns(self):
        sessions = select_sessions(subjects=[_KNOWN_SUBJECT], where=f"session_date = '{_KNOWN_DATE}'")
        if len(sessions) == 0:
            pytest.skip("No sessions found for known subject/date")
        trials = fetch_trials(sessions)
        assert "trial" in trials.columns
        assert "animal_response" in trials.columns
        assert "earned_reward" in trials.columns
        assert "subject_id" in trials.columns
        assert "session_id" in trials.columns

    def test_trials_belong_to_selected_sessions(self):
        sessions = select_sessions(subjects=[_KNOWN_SUBJECT], where=f"session_date = '{_KNOWN_DATE}'")
        if len(sessions) == 0:
            pytest.skip("No sessions found for known subject/date")
        trials = fetch_trials(sessions)
        assert set(trials["subject_id"]).issubset({_KNOWN_SUBJECT})

    def test_empty_sessions_returns_empty(self):
        empty = pd.DataFrame(columns=["_session_id", "subject_id", "session_date"])
        result = fetch_trials(empty)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_trial_count_reasonable(self):
        sessions = select_sessions(
            subjects=[_KNOWN_SUBJECT],
            columns=["finished_trials"],
            where=f"session_date = '{_KNOWN_DATE}'",
        )
        if len(sessions) == 0:
            pytest.skip("No sessions found")
        trials = fetch_trials(sessions)
        if pd.notna(sessions["finished_trials"].iloc[0]):
            expected = int(sessions["finished_trials"].iloc[0])
            # trial count should be within 20% of finished_trials (total_trials may differ)
            assert abs(len(trials) - expected) / max(expected, 1) < 0.2


class TestFetchUpstream:
    def test_returns_dataframe_with_asset_name(self):
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        sample = conn.sql(
            f"SELECT * FROM read_parquet('{UPSTREAM_SESSION_S3}') "
            f"WHERE subject_id = '{_KNOWN_SUBJECT}' LIMIT 5"
        ).df()
        enriched = _add_asset_name(sample)
        assert "asset_name" in enriched.columns
        co_rows = enriched[enriched["co_s3_nwb_uri"].notna()]
        if len(co_rows):
            assert co_rows["asset_name"].notna().all()
