"""少样本视觉参考：冻结 CLIP 的图像特征与已复核物品标签匹配，不把相似度当概率。"""
import numpy as np
from .schema import Item


class VisualSupport:
    """只加载无 pickle 的数值参考；开发评估可排除整个来源组，避免匹配自身。"""
    def __init__(self,path,labels,device):
        import torch
        with np.load(path,allow_pickle=False) as saved:
            self.features=torch.from_numpy(saved['features']).to(device)
            self.labels=saved['labels'].tolist();self.groups=saved['groups'].tolist()
        self.taxonomy_labels=labels
        if not set(self.labels)<=set(labels):raise ValueError('视觉参考标签与当前物品词表不一致。')
    def score(self,features,excluded_group=None):
        import torch
        scores=features@self.features.T
        result=torch.full((len(features),len(self.taxonomy_labels)),-1.,device=features.device)
        for i,label in enumerate(self.taxonomy_labels):
            selected=[j for j,(name,group) in enumerate(zip(self.labels,self.groups)) if name==label and group!=excluded_group]
            if selected:result[:,i]=scores[:,selected].max(dim=1).values
        return result


def classify_supported_region(text_scores,visual_scores,taxonomy,settings,fallback):
    """视觉参考必须同时超过相似度和跨类别差值门槛；证据不足仍用文本基线。"""
    if visual_scores is None:return fallback(text_scores,taxonomy,settings)
    items=taxonomy['items'];best=max(range(len(visual_scores)),key=visual_scores.__getitem__)
    def group(i):return items[i]['category'] if i<len(items) else 'background'
    category=group(best)
    rival=max(v for i,v in enumerate(visual_scores) if group(i)!=category)
    margin=visual_scores[best]-rival
    if visual_scores[best]<settings.get('visual_similarity_min',.65) or margin<settings.get('visual_margin_min',.04):
        return fallback(text_scores,taxonomy,settings)
    if best>=len(items):return None
    entry=items[best]
    return Item(name=entry['name'] if category else '待确认区域',label=entry['label'],category=category,
        uncertain=category is None,reason=entry['reason'],similarity=text_scores[best],
        visual_similarity=visual_scores[best],visual_margin=margin,classification_basis='visual_reference')
