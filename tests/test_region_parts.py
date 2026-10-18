"""局部碎片误检回归：只允许抑制被真实掩膜包住的低分未知区域。"""
import numpy as np
from garbage_vision.config import local_settings
from garbage_vision.local import prune_uncertain_parts
from garbage_vision.schema import Item


def candidate(category, similarity, label):
    return Item(name='软件检查区域', reason='软件边界样例', category=category,
                label=label, similarity=similarity, bbox=(0,0,8,8))


def test_contained_uncertain_fragment_removed_but_audited():
    whole=np.ones((8,8), dtype=bool); part=np.zeros((8,8), dtype=bool);part[:2,:2]=True
    items=[candidate('recyclable', .34, 'bottle'), candidate(None, .29, 'lamp')]
    kept, audit=prune_uncertain_parts(items, [whole,part], local_settings())
    assert kept==[items[0]] and audit[0]['candidate']['label']=='lamp'
    assert audit[0]['mask_containment']==1


def test_separate_masks_and_known_small_objects_are_not_hidden():
    whole=np.zeros((8,8), dtype=bool);whole[4:,:]=True
    part=np.zeros((8,8), dtype=bool);part[:2,:2]=True
    items=[candidate('recyclable', .34, 'bottle'), candidate(None, .29, 'lamp')]
    kept, audit=prune_uncertain_parts(items,[whole,part],local_settings())
    assert len(kept)==2 and not audit  # 框相同但真实区域不相交，不能误删。
    items[1]=candidate('hazardous', .29, 'lamp')
    kept, audit=prune_uncertain_parts(items,[np.ones((8,8)),part],local_settings())
    assert len(kept)==2 and not audit
