"""识别质量实验防泄漏：来源隔离、参考标签映射和候选数据来源不能被悄悄改变。"""
import json
from garbage_vision.config import ROOT,rules


def test_quality_holdout_is_not_used_by_reference_library():
    dev=json.loads((ROOT/'data/manifests/quality_dev.json').read_text(encoding='utf-8'))
    test=json.loads((ROOT/'data/manifests/quality_test.json').read_text(encoding='utf-8'))
    old_test=json.loads((ROOT/'data/manifests/test.json').read_text(encoding='utf-8'))
    for key in ['id','sha256','group_id']:
        assert not ({r[key] for r in dev}&{r[key] for r in test})
    assert not ({r['sha256'] for r in dev}&{r['sha256'] for r in old_test})
    for a in dev:
        assert all((int(a['dhash'],16)^int(b['dhash'],16)).bit_count()>5 for b in test)
    assert len(test)==40 and sum(not r['categories'] for r in test)==8
    assert all(r['reviewed_before_inference'] for r in dev+test)


def test_reference_semantics_do_not_turn_unknowns_into_other():
    dev=json.loads((ROOT/'data/manifests/quality_dev.json').read_text(encoding='utf-8'))
    taxonomy=rules();mapping={r['label']:r['category'] for r in taxonomy['items']}
    labels=set(mapping)|set(taxonomy['background_labels'])
    for row in dev:
        assert row['support_label'] in labels
        category=mapping.get(row['support_label'])
        assert row['categories']==([category] if category else [])
