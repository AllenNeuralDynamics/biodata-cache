"""Unit tests for zombie_squirrel.sync module."""

import json
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from zombie_squirrel.sync import hide_acorns, publish_squirrel_metadata


def _make_registry(mock_upn, mock_usi, mock_ugt, mock_basics, mock_d2r, mock_r2d, mock_qc, mock_smartspim):
    return {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "raw_to_derived": mock_r2d,
        "quality_control": mock_qc,
        "assets_smartspim": mock_smartspim,
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "foraging_sessions": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }


# --- hide_acorns ---

@patch("zombie_squirrel.sync.publish_squirrel_metadata")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_all_acorns_called_with_force_update(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_upn, mock_usi, mock_ugt, mock_d2r, mock_r2d, mock_qc, mock_smartspim = (MagicMock() for _ in range(7))
    mock_registry.__getitem__.side_effect = _make_registry(
        mock_upn, mock_usi, mock_ugt, mock_basics, mock_d2r, mock_r2d, mock_qc, mock_smartspim
    ).__getitem__

    hide_acorns()

    mock_upn.assert_called_once_with(force_update=True)
    mock_usi.assert_called_once_with(force_update=True)
    mock_ugt.assert_called_once_with(force_update=True)
    mock_basics.assert_called_once_with(force_update=True)
    mock_d2r.assert_called_once_with(force_update=True)
    mock_r2d.assert_not_called()
    mock_smartspim.assert_called_once_with(force_update=True)


@patch("zombie_squirrel.sync.publish_squirrel_metadata")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_qc_called_per_subject(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1", "sub2", None]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_qc = MagicMock()
    mock_registry.__getitem__.side_effect = _make_registry(
        MagicMock(), MagicMock(), MagicMock(), mock_basics, MagicMock(), MagicMock(), mock_qc, MagicMock()
    ).__getitem__

    hide_acorns()

    mock_qc.assert_has_calls(
        [call(subject_id="sub1", force_update=True), call(subject_id="sub2", force_update=True)],
        any_order=True,
    )
    assert mock_qc.call_count == 2


@patch("zombie_squirrel.sync.publish_squirrel_metadata")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_qc_skipped_when_no_subjects(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": [None, None]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_qc = MagicMock()
    mock_registry.__getitem__.side_effect = _make_registry(
        MagicMock(), MagicMock(), MagicMock(), mock_basics, MagicMock(), MagicMock(), mock_qc, MagicMock()
    ).__getitem__

    hide_acorns()

    mock_qc.assert_not_called()


@patch("zombie_squirrel.sync.publish_squirrel_metadata")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_publish_metadata_called_at_end(mock_registry, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_registry.__getitem__.side_effect = _make_registry(
        MagicMock(), MagicMock(), MagicMock(), mock_basics, MagicMock(), MagicMock(), MagicMock(), MagicMock()
    ).__getitem__

    hide_acorns()

    mock_publish.assert_called_once()


@patch("zombie_squirrel.sync.publish_squirrel_metadata")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_exception_from_acorn_propagates(mock_registry, mock_publish):
    mock_upn = MagicMock(side_effect=Exception("Update failed"))
    mock_registry.__getitem__.side_effect = _make_registry(
        mock_upn, MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()
    ).__getitem__

    with pytest.raises(Exception, match="Update failed"):
        hide_acorns()


# --- publish_squirrel_metadata ---

@patch("zombie_squirrel.sync.TREE")
def test_plant_called_with_squirrel_json_key(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    mock_tree.plant.assert_called_once()
    assert mock_tree.plant.call_args[0][0] == "squirrel.json"


@patch("zombie_squirrel.sync.TREE")
def test_published_json_contains_nine_acorns(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    payload = json.loads(mock_tree.plant.call_args[0][1])
    assert "acorns" in payload
    assert len(payload["acorns"]) == 12


@patch("zombie_squirrel.sync.TREE")
def test_published_json_acorn_names(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    payload = json.loads(mock_tree.plant.call_args[0][1])
    names = {a["name"] for a in payload["acorns"]}
    for expected in ("unique_project_names", "unique_subject_ids", "unique_genotypes",
                     "asset_basics", "source_data", "quality_control", "assets_smartspim",
                     "metadata_upgrade", "platform_fib", "platform_qc"):
        assert expected in names


@patch("zombie_squirrel.sync.TREE")
def test_qc_acorn_is_partitioned(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    payload = json.loads(mock_tree.plant.call_args[0][1])
    qc = next(a for a in payload["acorns"] if a["name"] == "quality_control")
    assert qc["partitioned"] is True
    assert qc["partition_key"] == "subject_id"
    assert qc["type"] == "asset"


@patch("zombie_squirrel.sync.TREE")
def test_non_qc_acorns_are_metadata_type(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    payload = json.loads(mock_tree.plant.call_args[0][1])
    non_metadata_names = {"quality_control", "behavior_curriculum", "platform_qc"}
    for acorn in payload["acorns"]:
        if acorn["name"] not in non_metadata_names:
            assert acorn["type"] == "metadata"
            assert acorn["partitioned"] is False


@patch("zombie_squirrel.sync.TREE")
def test_get_location_called_for_each_acorn(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    assert mock_tree.get_location.call_count == 12


@patch("zombie_squirrel.sync.TREE")
def test_qc_location_uses_partitioned_flag(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    assert call("qc", partitioned=True) in mock_tree.get_location.call_args_list


@patch("zombie_squirrel.sync.TREE")
def test_acorns_have_columns(mock_tree):
    mock_tree.get_location.return_value = "s3://bucket/path"
    publish_squirrel_metadata()
    payload = json.loads(mock_tree.plant.call_args[0][1])
    for acorn in payload["acorns"]:
        assert isinstance(acorn["columns"], list)
        assert len(acorn["columns"]) > 0


@patch("zombie_squirrel.sync.TREE")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_hide_acorns_calls_all_acorns(mock_registry, mock_tree):
    mock_upn, mock_usi, mock_ugt, mock_d2r, mock_r2d, mock_qc, mock_smartspim, mock_fib = (MagicMock() for _ in range(8))
    mock_basics = MagicMock(return_value=pd.DataFrame({"subject_id": ["subject1", "subject2"]}))
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "raw_to_derived": mock_r2d,
        "quality_control": mock_qc,
        "assets_smartspim": mock_smartspim,
        "metadata_upgrade": MagicMock(),
        "platform_fib": mock_fib,
        "foraging_sessions": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }[x]
    mock_tree.get_location.return_value = "s3://test-bucket/test"

    hide_acorns()

    mock_upn.assert_called_once_with(force_update=True)
    mock_usi.assert_called_once_with(force_update=True)
    mock_ugt.assert_called_once_with(force_update=True)
    mock_basics.assert_called_once_with(force_update=True)
    mock_d2r.assert_called_once_with(force_update=True)
    assert mock_qc.call_count == 2
    mock_qc.assert_any_call(subject_id="subject1", force_update=True)
    mock_qc.assert_any_call(subject_id="subject2", force_update=True)
    mock_fib.assert_called_once_with(force_update=True)


@patch("zombie_squirrel.sync.TREE")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_hide_acorns_empty_registry(mock_registry, mock_tree):
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
        "assets_smartspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "foraging_sessions": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }[x]
    mock_tree.get_location.return_value = "s3://test-bucket/test"

    hide_acorns()

    mock_upn.assert_called_once_with(force_update=True)
    mock_usi.assert_called_once_with(force_update=True)
    mock_ugt.assert_called_once_with(force_update=True)
    mock_basics.assert_called_once_with(force_update=True)
    mock_d2r.assert_called_once_with(force_update=True)
    mock_qc.assert_not_called()


@patch("zombie_squirrel.sync.TREE")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_hide_acorns_single_acorn(mock_registry, mock_tree):
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
        "assets_smartspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "foraging_sessions": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }[x]
    mock_tree.get_location.return_value = "s3://test-bucket/test"

    hide_acorns()

    mock_qc.assert_called_once_with(subject_id="subject1", force_update=True)


@patch("zombie_squirrel.sync.TREE")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_hide_acorns_acorn_order_independent(mock_registry, mock_tree):
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
        "assets_smartspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "foraging_sessions": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }[x]
    mock_tree.get_location.return_value = "s3://test-bucket/test"

    hide_acorns()

    assert mock_qc.call_count == 5
    for sub_id in ["sub1", "sub2", "sub3", "sub4", "sub5"]:
        mock_qc.assert_any_call(subject_id=sub_id, force_update=True)


@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_hide_acorns_propagates_exceptions(mock_registry):
    mock_upn = MagicMock(side_effect=Exception("Update failed"))
    mock_registry.__getitem__.side_effect = lambda x: {
        "unique_project_names": mock_upn,
        "unique_subject_ids": MagicMock(),
        "unique_genotypes": MagicMock(),
        "asset_basics": MagicMock(),
        "source_data": MagicMock(),
        "raw_to_derived": MagicMock(),
        "quality_control": MagicMock(),
        "assets_smartspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "foraging_sessions": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }[x]

    with pytest.raises(Exception, match="Update failed"):
        hide_acorns()

    mock_upn.assert_called_once_with(force_update=True)
