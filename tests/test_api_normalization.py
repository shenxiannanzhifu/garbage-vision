"""真实故障类型回归：一条矛盾结果不能清空其他有效物品，也不能猜成确定类别。"""
import json
import pytest
from garbage_vision.api_normalization import normalize_api_response


def test_conflicting_item_is_unknown_and_valid_neighbor_survives():
    text=json.dumps({'items':[
        {'name':'果皮','category':'kitchen','reason':'日常果皮','uncertain':False},
        {'name':'材质不清的物品','category':'other','reason':'不能确认材质','uncertain':True}]},ensure_ascii=False)
    items,audit=normalize_api_response(text)
    assert len(items)==2 and items[0].category=='kitchen'
    assert items[1].category is None and items[1].uncertain
    assert audit[0]['original_category']=='other'


def test_null_category_stays_unknown():
    items,audit=normalize_api_response('{"items":[{"name":"电池","category":null,"reason":"未知类型","uncertain":false}]}')
    assert items[0].category is None and items[0].uncertain
    assert audit


@pytest.mark.parametrize('text',[
    '{"items":[{"name":"瓶","category":"可回收物","reason":"测试","uncertain":false}]}',
    '{"items":[{"name":"瓶","category":"recyclable","reason":"测试","uncertain":"false"}]}',
    '{"items":[{"name":"瓶","category":"recyclable","reason":"测试","uncertain":false,"confidence":0.9}]}',
    '{"items":['
])
def test_normalization_does_not_invent_missing_or_invalid_fields(text):
    with pytest.raises(ValueError):normalize_api_response(text)
