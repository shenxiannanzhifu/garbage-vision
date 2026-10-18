import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from garbage_vision.config import weight_hash
from scripts.resume_nexavlinks_reviewed import accounted_cost


def test_failure_requires_matching_review_and_counts_full_reservation():
    with TemporaryDirectory() as folder:
        _check_ledger(Path(folder))


def _check_ledger(tmp_path):
    marker = tmp_path/'sample.started.json'
    target = tmp_path/'sample.json'
    marker.write_text(json.dumps({'reserved_nex': 0.218625}))
    with pytest.raises(ValueError, match='Unresolved'):
        accounted_cost(tmp_path, {})
    target.write_text(json.dumps({'id':'sample', 'result':{'status':'error'}, 'estimated_cost_nex':None}))
    with pytest.raises(ValueError, match='Unreviewed'):
        accounted_cost(tmp_path, {})
    review = {'sample':{'result_sha256':weight_hash(target), 'marker_sha256':weight_hash(marker),
        'action':'skip_without_retry', 'actual_cost_nex':0.009252}}
    assert accounted_cost(tmp_path, review) == (1, 0.218625)
    review['sample']['actual_cost_nex'] = 1
    with pytest.raises(ValueError, match='exceeds'):
        accounted_cost(tmp_path, review)
    review['sample']['actual_cost_nex'] = 0.009252
    review['sample']['actual_cost_nex'] = None
    with pytest.raises(ValueError, match='explicit user authorization'):
        accounted_cost(tmp_path, review)
    review['sample']['unknown_cost_reserved_authorized'] = True
    assert accounted_cost(tmp_path, review) == (1, 0.218625)
    target.write_text(target.read_text()+' ')
    with pytest.raises(ValueError, match='changed'):
        accounted_cost(tmp_path, review)
