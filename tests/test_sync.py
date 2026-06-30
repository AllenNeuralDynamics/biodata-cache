"""Unit tests for biodata_cache.sync module."""

import json
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from biodata_cache.sync import publish_cache_registry, update_all_tables


def _make_registry(mock_upn, mock_usi, mock_ugt, mock_basics, mock_d2r, mock_r2d, mock_qc, mock_smartspim):
    return {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "raw_to_derived": mock_r2d,
        "quality_control": mock_qc,
        "platform_smartspim": mock_smartspim,
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }


# --- update_all_tables ---


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_all_tables_called_with_force_update(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_upn, mock_usi, mock_ugt, mock_d2r, mock_r2d, mock_qc, mock_smartspim = (MagicMock() for _ in range(7))
    mock_registry.__getitem__.side_effect = _make_registry(
        mock_upn, mock_usi, mock_ugt, mock_basics, mock_d2r, mock_r2d, mock_qc, mock_smartspim
    ).__getitem__

    update_all_tables()

    mock_basics.assert_called_once_with(force_update=True)
    mock_upn.assert_called_once_with(force_update=True)
    mock_usi.assert_called_once_with(force_update=True)
    mock_ugt.assert_called_once_with(force_update=True)
    mock_d2r.assert_called_once_with(force_update=True)
    mock_r2d.assert_not_called()
    mock_smartspim.assert_called_once_with(force_update=True)


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_qc_called_per_subject(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1", "sub2", None]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_qc = MagicMock()
    mock_registry.__getitem__.side_effect = _make_registry(
        MagicMock(), MagicMock(), MagicMock(), mock_basics, MagicMock(), MagicMock(), mock_qc, MagicMock()
    ).__getitem__

    update_all_tables()

    mock_qc.assert_has_calls(
        [call(subject_id="sub1", force_update=True), call(subject_id="sub2", force_update=True)],
        any_order=True,
    )
    assert mock_qc.call_count == 2


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_qc_skipped_when_no_subjects(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": [None, None]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_qc = MagicMock()
    mock_registry.__getitem__.side_effect = _make_registry(
        MagicMock(), MagicMock(), MagicMock(), mock_basics, MagicMock(), MagicMock(), mock_qc, MagicMock()
    ).__getitem__

    update_all_tables()

    mock_qc.assert_not_called()


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_publish_metadata_called_at_end(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_registry.__getitem__.side_effect = _make_registry(
        MagicMock(), MagicMock(), MagicMock(), mock_basics, MagicMock(), MagicMock(), MagicMock(), MagicMock()
    ).__getitem__

    update_all_tables()

    mock_publish.assert_called_once()


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_exception_from_table_propagates(mock_registry, mock_publish):
    mock_upn = MagicMock(side_effect=Exception("Update failed"))
    mock_registry.__getitem__.side_effect = _make_registry(
        mock_upn, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()
    ).__getitem__

    with pytest.raises(Exception, match="Update failed"):
        update_all_tables()


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_fast_only_skips_slow_tables(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_qc = MagicMock()
    mock_smartspim = MagicMock()
    mock_df_sessions = MagicMock(return_value=pd.DataFrame({"subject_id": []}))
    mock_curriculum = MagicMock()
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": MagicMock(),
        "unique_subject_ids": MagicMock(),
        "unique_genotypes": MagicMock(),
        "asset_basics": mock_basics,
        "source_data": MagicMock(),
        "raw_to_derived": MagicMock(),
        "quality_control": mock_qc,
        "platform_smartspim": mock_smartspim,
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": mock_df_sessions,
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": mock_curriculum,
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]

    update_all_tables(fast=True, slow=False)

    mock_basics.assert_called_once_with(force_update=True)
    mock_qc.assert_not_called()
    mock_smartspim.assert_not_called()
    mock_df_sessions.assert_not_called()
    mock_curriculum.assert_not_called()


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_slow_only_skips_fast_tables(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_upn = MagicMock()
    mock_usi = MagicMock()
    mock_ugt = MagicMock()
    mock_d2r = MagicMock()
    mock_upgrade = MagicMock()
    mock_fib = MagicMock()
    mock_qc = MagicMock()
    mock_smartspim = MagicMock()
    mock_df_sessions = MagicMock(return_value=pd.DataFrame({"subject_id": []}))
    mock_curriculum = MagicMock()
    mock_platform_qc = MagicMock()
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "raw_to_derived": MagicMock(),
        "quality_control": mock_qc,
        "platform_smartspim": mock_smartspim,
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": mock_upgrade,
        "platform_fib": mock_fib,
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": mock_df_sessions,
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": mock_curriculum,
        "platform_qc": mock_platform_qc,
        "time_to_qc": MagicMock(),
    }[x]

    update_all_tables(fast=False, slow=True)

    mock_basics.assert_called_once_with(force_update=True)
    mock_upn.assert_not_called()
    mock_usi.assert_not_called()
    mock_ugt.assert_not_called()
    mock_d2r.assert_not_called()
    mock_upgrade.assert_not_called()
    mock_fib.assert_not_called()
    mock_platform_qc.assert_not_called()
    mock_qc.assert_called_once_with(subject_id="sub1", force_update=True)
    mock_smartspim.assert_called_once_with(force_update=True)
    mock_df_sessions.assert_called_once_with(force_update=True)
    mock_curriculum.assert_called_once_with(force_update=True)


# --- publish_cache_registry ---


@patch("biodata_cache.sync.BACKEND")
def test_plant_called_with_squirrel_json_key(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    mock_backend.put_json.assert_called_once()
    assert mock_backend.put_json.call_args[0][0] == "cache_registry.json"


@patch("biodata_cache.sync.BACKEND")
def test_published_json_contains_nine_tables(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    payload = json.loads(mock_backend.put_json.call_args[0][1])
    assert "tables" in payload
    assert len(payload["tables"]) == 18


@patch("biodata_cache.sync.BACKEND")
def test_published_json_table_names(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    payload = json.loads(mock_backend.put_json.call_args[0][1])
    names = {a["name"] for a in payload["tables"]}
    for expected in (
        "unique_project_names",
        "unique_subject_ids",
        "unique_genotypes",
        "asset_basics",
        "source_data",
        "quality_control",
        "platform_smartspim",
        "metadata_upgrade",
        "platform_fib",
        "platform_qc",
        "platform_dynamic_foraging_sessions",
        "platform_dynamic_foraging_trials",
        "platform_dynamic_foraging_events",
    ):
        assert expected in names


@patch("biodata_cache.sync.BACKEND")
def test_qc_table_fn_is_partitioned(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    payload = json.loads(mock_backend.put_json.call_args[0][1])
    qc = next(a for a in payload["tables"] if a["name"] == "quality_control")
    assert qc["partitioned"] is True
    assert qc["partition_key"] == "subject_id"
    assert qc["type"] == "asset"


@patch("biodata_cache.sync.BACKEND")
def test_non_qc_table_fns_are_metadata_type(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    payload = json.loads(mock_backend.put_json.call_args[0][1])
    non_metadata_names = {
        "quality_control",
        "behavior_curriculum",
        "platform_qc",
        "platform_dynamic_foraging_sessions",
        "platform_dynamic_foraging_trials",
        "platform_dynamic_foraging_events",
        "platform_fib_traces",
        "platform_mouselight",
    }
    for cache_table in payload["tables"]:
        if cache_table["name"] not in non_metadata_names:
            assert cache_table["type"] == "metadata"
            assert cache_table["partitioned"] is False


@patch("biodata_cache.sync.BACKEND")
def test_get_location_called_for_each_table(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    assert mock_backend.get_location.call_count == 18

@patch("biodata_cache.sync.BACKEND")
def test_qc_location_uses_partitioned_flag(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    assert call("qc", partitioned=True) in mock_backend.get_location.call_args_list


@patch("biodata_cache.sync.BACKEND")
def test_tables_have_columns(mock_backend):
    mock_backend.get_location.return_value = "s3://bucket/path"
    publish_cache_registry()
    payload = json.loads(mock_backend.put_json.call_args[0][1])
    for cache_table in payload["tables"]:
        assert isinstance(cache_table["columns"], list)
        assert len(cache_table["columns"]) > 0


@patch("biodata_cache.sync.BACKEND")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_update_all_tables_calls_all_tables(mock_registry, mock_backend):
    mock_upn, mock_usi, mock_ugt, mock_d2r, mock_r2d, mock_qc, mock_smartspim, mock_fib = (
        MagicMock() for _ in range(8)
    )
    mock_basics = MagicMock(return_value=pd.DataFrame({"subject_id": ["subject1", "subject2"]}))
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "raw_to_derived": mock_r2d,
        "quality_control": mock_qc,
        "platform_smartspim": mock_smartspim,
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": mock_fib,
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]
    mock_backend.get_location.return_value = "s3://test-bucket/test"

    update_all_tables()

    mock_upn.assert_called_once_with(force_update=True)
    mock_usi.assert_called_once_with(force_update=True)
    mock_ugt.assert_called_once_with(force_update=True)
    mock_basics.assert_called_once_with(force_update=True)
    mock_d2r.assert_called_once_with(force_update=True)
    assert mock_qc.call_count == 2
    mock_qc.assert_any_call(subject_id="subject1", force_update=True)
    mock_qc.assert_any_call(subject_id="subject2", force_update=True)
    mock_fib.assert_called_once_with(force_update=True)


@patch("biodata_cache.sync.BACKEND")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_update_all_tables_empty_registry(mock_registry, mock_backend):
    mock_upn, mock_usi, mock_ugt, mock_d2r, mock_r2d, mock_qc = (MagicMock() for _ in range(6))
    mock_basics = MagicMock(return_value=pd.DataFrame({"subject_id": []}))
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "raw_to_derived": mock_r2d,
        "quality_control": mock_qc,
        "platform_smartspim": MagicMock(),
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]
    mock_backend.get_location.return_value = "s3://test-bucket/test"

    update_all_tables()

    mock_upn.assert_called_once_with(force_update=True)
    mock_usi.assert_called_once_with(force_update=True)
    mock_ugt.assert_called_once_with(force_update=True)
    mock_basics.assert_called_once_with(force_update=True)
    mock_d2r.assert_called_once_with(force_update=True)
    mock_qc.assert_not_called()


@patch("biodata_cache.sync.BACKEND")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_update_all_tables_single_table(mock_registry, mock_backend):
    mock_basics = MagicMock(return_value=pd.DataFrame({"subject_id": ["subject1"]}))
    mock_qc = MagicMock()
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": MagicMock(),
        "unique_subject_ids": MagicMock(),
        "unique_genotypes": MagicMock(),
        "asset_basics": mock_basics,
        "source_data": MagicMock(),
        "raw_to_derived": MagicMock(),
        "quality_control": mock_qc,
        "platform_smartspim": MagicMock(),
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]
    mock_backend.get_location.return_value = "s3://test-bucket/test"

    update_all_tables()

    mock_qc.assert_called_once_with(subject_id="subject1", force_update=True)


@patch("biodata_cache.sync.BACKEND")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_update_all_tables_order_independent(mock_registry, mock_backend):
    mock_basics = MagicMock(return_value=pd.DataFrame({"subject_id": ["sub1", "sub2", "sub3", "sub4", "sub5"]}))
    mock_qc = MagicMock()
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": MagicMock(),
        "unique_subject_ids": MagicMock(),
        "unique_genotypes": MagicMock(),
        "asset_basics": mock_basics,
        "source_data": MagicMock(),
        "raw_to_derived": MagicMock(),
        "quality_control": mock_qc,
        "platform_smartspim": MagicMock(),
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]
    mock_backend.get_location.return_value = "s3://test-bucket/test"

    update_all_tables()

    assert mock_qc.call_count == 5
    for sub_id in ["sub1", "sub2", "sub3", "sub4", "sub5"]:
        mock_qc.assert_any_call(subject_id=sub_id, force_update=True)


@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_update_all_tables_propagates_exceptions(mock_registry):
    mock_upn = MagicMock(side_effect=Exception("Update failed"))
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": mock_upn,
        "unique_subject_ids": MagicMock(),
        "unique_genotypes": MagicMock(),
        "asset_basics": MagicMock(),
        "source_data": MagicMock(),
        "raw_to_derived": MagicMock(),
        "quality_control": MagicMock(),
        "platform_smartspim": MagicMock(),
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]

    with pytest.raises(Exception, match="Update failed"):
        update_all_tables()

    mock_upn.assert_called_once_with(force_update=True)


def _registry_with_fib(mock_basics, mock_fib_traces):
    return lambda x: {
        "unique_project_names": MagicMock(),
        "unique_subject_ids": MagicMock(),
        "unique_genotypes": MagicMock(),
        "asset_basics": mock_basics,
        "source_data": MagicMock(),
        "raw_to_derived": MagicMock(),
        "quality_control": MagicMock(),
        "platform_smartspim": MagicMock(),
        "platform_exaspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "platform_fib_traces": mock_fib_traces,
        "platform_mouselight": MagicMock(),
        "platform_dynamic_foraging_sessions": MagicMock(return_value=pd.DataFrame({"subject_id": []})),
        "platform_dynamic_foraging_trials": MagicMock(),
        "platform_dynamic_foraging_events": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
        "time_to_qc": MagicMock(),
    }[x]


def _fib_basics():
    return pd.DataFrame(
        {
            "subject_id": ["sub1", "sub2"],
            "name": ["asset1", "asset2"],
            "modalities": [["fib"], ["behavior"]],
            "data_level": ["derived", "derived"],
        }
    )


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_fib_traces_called_per_fib_asset(mock_registry, mock_publish):
    mock_basics = MagicMock(return_value=_fib_basics())
    mock_fib_traces = MagicMock()
    mock_registry.__getitem__.side_effect = _registry_with_fib(mock_basics, mock_fib_traces)

    update_all_tables()

    mock_fib_traces.assert_called_once_with(asset_name="asset1", force_update=True)


@patch("biodata_cache.sync.publish_cache_registry")
@patch("biodata_cache.sync.as_completed")
@patch("biodata_cache.sync.TABLE_REGISTRY")
def test_fib_traces_fallback_sequential_on_concurrent_failure(mock_registry, mock_as_completed, mock_publish):
    mock_basics = MagicMock(return_value=_fib_basics())
    mock_fib_traces = MagicMock()
    mock_registry.__getitem__.side_effect = _registry_with_fib(mock_basics, mock_fib_traces)

    failed_future = MagicMock()
    failed_future.result.side_effect = RuntimeError("Executor failed")
    mock_as_completed.return_value = [failed_future]

    update_all_tables()

    mock_fib_traces.assert_any_call(asset_name="asset1", force_update=True)

