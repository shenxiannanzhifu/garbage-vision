"""用可以手算的多标签样例核验指标和数据对齐，绝不用正式测试预测调评分。"""
import pytest
from garbage_vision.evaluation import set_scores, score_records


def record(image_id, predicted, status='success'):
    return {'id': image_id, 'result': {'source_sha256': image_id, 'method': 'api', 'status': status,
            'items': [{'category': c} for c in predicted], 'elapsed_seconds': 1, 'load_seconds': 0}}


def test_hand_calculated_sets_and_failure_counted():
    manifest = [{'id': 'a', 'sha256': 'a', 'categories': ['recyclable', 'kitchen']},
                {'id': 'b', 'sha256': 'b', 'categories': ['hazardous']},
                {'id': 'c', 'sha256': 'c', 'categories': ['other']}]
    result = score_records(manifest, [record('a', ['recyclable', None]),
                           record('b', ['hazardous', 'other']), record('c', [], 'error')])
    assert result['mean_per_image_precision'] == pytest.approx(.5)
    assert result['mean_per_image_recall'] == pytest.approx(.5)
    assert result['mean_per_image_f1'] == pytest.approx(4/9)
    assert result['micro']['f1'] == pytest.approx(4/7)
    assert result['failure_rate'] == pytest.approx(1/3)
    assert result['exact_set_accuracy'] == 0
    assert result['unknown_image_rate'] == pytest.approx(1/3)
    assert result['per_category']['other']['fn'] == 1
    assert result['per_category']['other']['fp'] == 1


def test_empty_unknown_and_false_positive_conventions():
    assert set_scores({'other'}, set())['f1'] == 0
    assert set_scores(set(), {'other'})['f1'] == 0
    assert set_scores(set(), set())['f1'] == 1
    assert not set_scores(set(), set(), False)['exact_match']
    assert set_scores(set(), set(), False)['f1'] == 0


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'wrong-hash', 'invalid-category'])
def test_invalid_evidence_is_not_silently_scored(problem):
    manifest = [{'id': 'a', 'sha256': 'a', 'categories': ['other']}]
    rows = [record('a', ['other'])]
    if problem == 'missing': rows = []
    if problem == 'duplicate': rows *= 2
    if problem == 'wrong-hash': rows[0]['result']['source_sha256'] = 'different'
    if problem == 'invalid-category': rows[0]['result']['items'][0]['category'] = 'new-class'
    with pytest.raises(ValueError): score_records(manifest, rows)
