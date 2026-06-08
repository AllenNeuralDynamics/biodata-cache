"""Additional tests for sync module coverage."""

from unittest.mock import MagicMock, patch

import pandas as pd

from zombie_squirrel.sync import hide_acorns


@patch("zombie_squirrel.sync.publish_squirrel_metadata")
@patch("zombie_squirrel.sync.as_completed")
@patch("zombie_squirrel.sync.ACORN_REGISTRY")
def test_hide_acorns_fallback_sequential_on_concurrent_failure(mock_registry, mock_as_completed, mock_publish):
    df_basics = pd.DataFrame({"subject_id": ["sub1", "sub2"]})
    mock_basics = MagicMock(return_value=df_basics)
    mock_upn, mock_usi, mock_ugt, mock_d2r = (MagicMock() for _ in range(4))

    call_count = [0]

    def qc_side_effect(*args, **kwargs):
        call_count[0] += 1
        return pd.DataFrame()

    mock_qc = MagicMock(side_effect=qc_side_effect)

    mock_registry.__getitem__.side_effect = {
        "unique_project_names": mock_upn,
        "unique_subject_ids": mock_usi,
        "unique_genotypes": mock_ugt,
        "asset_basics": mock_basics,
        "source_data": mock_d2r,
        "quality_control": mock_qc,
        "assets_smartspim": MagicMock(),
        "metadata_upgrade": MagicMock(),
        "platform_fib": MagicMock(),
        "foraging_session": MagicMock(),
        "behavior_curriculum": MagicMock(),
        "platform_qc": MagicMock(),
    }.__getitem__

    failed_future = MagicMock()
    failed_future.result.side_effect = RuntimeError("Executor failed")
    mock_as_completed.return_value = [failed_future]

    hide_acorns()

    assert call_count[0] >= 2
    mock_publish.assert_called_once()
