import pytest
from garbage_vision.schema import Item,InferenceResult
from garbage_vision.recall import supplement_regions

def item(label='plastic bottle',category='recyclable',box=(1,1,20,20),margin=.06):
    return Item(name=label,label=label,category=category,bbox=box,reason='Visible evidence',similarity=.32,
                category_margin=margin,mask_quality=.95 if box else None)

def result(items,image='same',status='success'):
    return InferenceResult(image_id=image,source_sha256='hash',image_size=(100,100),method='local',
        model='test',status=status,items=items)

def combine(a,b,mode='empty-only'):
    return supplement_regions(a,b,margin_min=.04,mode=mode)

def test_empty_detector_recovers_real_region_without_mutating_components():
    a,b=result([]),result([item()]);r=combine(a,b)
    assert r.categories=={'recyclable'} and r.items[0].mask_quality==.95
    assert not a.items and b.items[0].reason=='Visible evidence'
    assert r.items[0].detection_confidence is None

def test_unknown_scene_and_weak_evidence_are_not_promoted():
    b=result([item(category=None),item(box=None),item(margin=.02)])
    assert not combine(result([]),b).items

def test_confirmed_detector_blocks_empty_only_but_allows_spatially_separate_recovery():
    a=result([item()]);b=result([item('used tissue','other',(50,50,70,70))])
    assert combine(a,b).categories=={'recyclable'}
    assert combine(a,b,'uncovered').categories=={'recyclable','other'}

def test_overlap_conflict_is_not_silently_added_as_another_object():
    r=combine(result([item()]),result([item('apple core','kitchen')]),'uncovered')
    assert r.categories=={'recyclable'} and r.metadata['recall_supplement']['rejected_overlap']

@pytest.mark.parametrize('other',[result([],image='different'),result([],status='error')])
def test_mismatched_or_failed_input_cannot_be_reported_as_success(other):
    with pytest.raises(ValueError):combine(result([]),other)
