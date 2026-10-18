"""保守规范化模型的不确定状态：只撤销矛盾条目的确定类别，不补造类别或丢弃有效条目。"""
import re
from .schema import Item


def normalize_api_response(text):
    """先严格校验字段；uncertain=true 与已知类别冲突时转成 null，并返回审计记录。"""
    from .api import APIResponse
    if not isinstance(text,str) or len(text)>50000:raise ValueError('模型返回内容为空或过长。')
    cleaned=text.strip()
    if cleaned.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',cleaned,re.S)
        if not match:raise ValueError('模型返回的 JSON 围栏不完整。')
        cleaned=match.group(1)
    payload=APIResponse.model_validate_json(cleaned)
    items=[];audit=[]
    for index,entry in enumerate(payload.items):
        fields=entry.model_dump()
        if entry.uncertain and entry.category is not None:
            audit.append({'item_index':index,'original_category':entry.category,
                          'action':'uncertain_category_cleared','reason':'模型声明不确定，撤销矛盾的确定类别。'})
            fields['category']=None
        elif entry.category is None and not entry.uncertain:
            audit.append({'item_index':index,'action':'null_category_marked_uncertain'})
            fields['uncertain']=True
        items.append(Item(**fields))
    return items,audit
