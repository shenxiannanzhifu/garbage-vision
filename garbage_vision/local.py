"""本地方案：SAM2 自动分割候选区域，CLIP 对区域分类，再映射四类。

主入口 infer_local 接受与 API 完全相同的 RGB 原图。SAM 分数是掩膜质量，
CLIP 分数是余弦相似度；两者都不是经过校准的垃圾分类概率。
"""
from functools import lru_cache
import json
import os
from threading import RLock
import time
from .config import ROOT, fingerprint, local_settings, rules, weight_hash
from .schema import InferenceResult, Item

_creation_lock=RLock()

def box_iou(a,b):
    """原图 XYXY 的框交并比，用于删除同一物体的高度重合候选。"""
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/union if union else 0

def classify_region(scores, taxonomy, settings):
    """跨类别比较最佳相似度；背景获胜时跳过，分类证据不足则返回未知。"""
    items=taxonomy['items']; best=max(range(len(scores)),key=scores.__getitem__)
    if best>=len(items): return None
    entry=items[best]; category=entry['category']
    # 同属可回收物的塑料瓶与玻璃瓶可能难区分，不因此把四分类也强行判错。
    rival=max(v for i,v in enumerate(scores) if i>=len(items) or items[i]['category']!=category)
    margin=scores[best]-rival
    known=category is not None and scores[best]>=settings['similarity_min'] and margin>=settings['category_margin_min']
    if scores[best]<settings['similarity_min']: return None
    reason=entry['reason'] if known else '不能确认物品类型或投放类别。外观候选：'+entry['name']+'；需结合完整物品、材质和用途人工核对。'
    return Item(name=entry['name'] if known else '待确认区域',label=entry['label'],category=category if known else None,
                uncertain=not known,reason=reason,similarity=scores[best],category_margin=margin)


def prune_uncertain_parts(items, masks, settings):
    """删除完整已知物体内的低分未知碎片；用真实掩膜包含关系，不能只看外接框。

    保留被过滤的原始候选供审计；不抑制确定类别的小物品和掩膜不相交的独立物品。
    """
    import numpy as np
    binary=[np.asarray(mask,dtype=bool) for mask in masks]
    areas=[int(mask.sum()) for mask in binary]
    kept=[]; suppressed=[]
    for i,item in enumerate(items):
        parent=None
        if item.category is None and areas[i]:
            for j,whole in enumerate(items):
                if whole.category is None or not areas[j]:continue
                if whole.similarity-item.similarity < settings['part_similarity_gap']:continue
                if areas[i]/areas[j] > settings['part_max_area_ratio']:continue
                containment=float(np.count_nonzero(binary[i]&binary[j]))/areas[i]
                if containment >= settings['part_mask_containment']:
                    parent={'parent_label':whole.label,'parent_bbox':whole.bbox,
                            'mask_containment':containment,'area_ratio':areas[i]/areas[j]};break
        if parent:
            suppressed.append({'candidate':item.model_dump(),**parent,
                               'reason':'较高分的已知物体内包含的低分未知局部区域；不重复作为独立物品。'})
        else:kept.append(item)
    return kept,suppressed

class LocalEngine:
    """缓存权重与文本向量；锁保护 SAM 的图像缓存，防止并发图片相互污染。"""
    def __init__(self,settings,taxonomy,device):
        start=time.perf_counter()
        (ROOT/'.local/ultralytics/Ultralytics').mkdir(parents=True,exist_ok=True)
        os.environ['YOLO_CONFIG_DIR']=str(ROOT/'.local/ultralytics')
        os.environ['YOLO_AUTOINSTALL']='false'
        import torch,clip
        from ultralytics import SAM
        from ultralytics.models.sam.predict import SAM2Predictor
        self.torch=torch;self.settings=settings;self.taxonomy=taxonomy;self.device=device;self.lock=RLock()
        class RegionPredictor(SAM2Predictor):
            def generate(self,im,**kwargs):
                return super().generate(im,points_stride=settings['points_stride'],
                    points_batch_size=settings['points_batch_size'],crop_n_layers=settings.get('crop_n_layers',0),**kwargs)
        self.predictor_class=RegionPredictor
        sam_path=ROOT/settings['sam_weights'];clip_path=ROOT/settings['clip_weights']
        for path in [sam_path,clip_path]:
            if not path.is_file():raise FileNotFoundError('缺少模型文件，请先运行 scripts/download_weights.py：'+path.name)
        self.sam=SAM(str(sam_path))
        self.clip,self.preprocess=clip.load(str(clip_path),device=device)
        self.labels=[x['label'] for x in taxonomy['items']]+taxonomy['background_labels']
        with torch.inference_mode():
            features=self.clip.encode_text(clip.tokenize(['a photo of '+x for x in self.labels]).to(device)).float()
            self.text_features=features/features.norm(dim=-1,keepdim=True)
        self.weight_hashes={p.name:weight_hash(p) for p in [sam_path,clip_path]}
        self.load_seconds=time.perf_counter()-start
        self.calls=0

    def infer(self,source):
        """颜色约定：传 PIL RGB 给 Ultralytics；CLIP 接收 RGB 裁剪，绝不手动错换 BGR。"""
        with self.lock,self.torch.inference_mode():
            started=time.perf_counter();settings=self.settings;width,height=source.image.size
            result=self.sam.predict(source.image,device=self.device,verbose=False,imgsz=1024,
                predictor=self.predictor_class,conf=settings['mask_score_min'],iou=.7)[0]
            boxes=result.boxes.xyxy.cpu().tolist();qualities=result.boxes.conf.cpu().tolist()
            from PIL import Image
            import numpy as np
            candidates=[];candidate_masks=[];crops=[];regions=[]
            masks=result.masks.data.cpu().numpy() if result.masks is not None else []
            for box,quality,mask in zip(boxes,qualities,masks):
                x1,y1,x2,y2=box
                x1=max(0,x1);y1=max(0,y1);x2=min(width,x2);y2=min(height,y2)
                bw,bh=x2-x1,y2-y1
                if min(bw,bh)<settings['min_box_side'] or bw*bh/(width*height)<settings['min_area_fraction']:continue
                if bw*bh/(width*height)>settings.get('max_area_fraction',1):continue
                pad=settings['crop_padding']*max(bw,bh)
                crop=source.image.crop((max(0,x1-pad),max(0,y1-pad),min(width,x2+pad),min(height,y2+pad)))
                # 背景区域的外接框也可能包住真正的物品。用真实掩膜去掉区域外像素，
                # 避免把整张桌面因框内有瓶子而认成第二个瓶子。
                if settings.get('region_input')=='mask-on-gray':
                    mask_image=Image.fromarray((mask.astype(np.uint8)*255)).crop((max(0,x1-pad),max(0,y1-pad),min(width,x2+pad),min(height,y2+pad)))
                    crop=Image.composite(crop,Image.new('RGB',crop.size,(127,127,127)),mask_image)
                crops.append(self.preprocess(crop));regions.append(((x1,y1,x2,y2),quality,mask))
            # 小批量编码防止复杂图片的区域数造成显存溢出。
            scores=[]
            for start in range(0,len(crops),16):
                tensor=self.torch.stack(crops[start:start+16]).to(self.device)
                feature=self.clip.encode_image(tensor).float();feature/=feature.norm(dim=-1,keepdim=True)
                scores.extend((feature@self.text_features.T).cpu().tolist())
            for (box,quality,mask),similarities in zip(regions,scores):
                item=classify_region(similarities,self.taxonomy,settings)
                if item:
                    item.bbox=tuple(round(v,2) for v in box);item.mask_quality=quality;candidates.append(item);candidate_masks.append(mask)
            candidate_count=len(candidates)
            candidates,suppressed=prune_uncertain_parts(candidates,candidate_masks,settings)
            # 分割可能包含同物体的整体与局部；只删除高度重合框，不声称可精确计数。
            kept=[]
            for item in sorted(candidates,key=lambda x:x.similarity,reverse=True):
                if not any(box_iou(item.bbox,x.bbox)>settings['duplicate_iou'] for x in kept):kept.append(item)
            elapsed=time.perf_counter()-started;warm=self.calls>0;self.calls+=1
            return InferenceResult(image_id=source.image_id,source_sha256=source.source_sha256,image_size=source.image.size,
                method='local',model='SAM2.1-tiny + CLIP ViT-B/32',status='success',items=kept[:settings['max_objects']],
                elapsed_seconds=elapsed,load_seconds=0 if warm else self.load_seconds,cache_hit=warm,
                metadata={'device':self.device,'region_count':len(boxes),'candidate_count':candidate_count,
                    'suppressed_uncertain_parts':suppressed,
                    'truncated':len(kept)>settings['max_objects'],'weight_sha256':self.weight_hashes,
                    'config_sha256':fingerprint(settings),'rules_sha256':fingerprint(self.taxonomy),
                    'config':settings,'score_note':'mask_quality 为 SAM 预测掩膜质量；similarity 为 CLIP 余弦相似度。均非垃圾类别概率。'})

@lru_cache(maxsize=2)
def _engine(config_text,rules_text,device,weight_state):
    return LocalEngine(json.loads(config_text),json.loads(rules_text),device)

def infer_local(source,settings=None):
    """有 CUDA 时优先使用；显存不足或 CUDA 运行错误时释放缓存并明确回退 CPU。"""
    import torch
    settings=dict(settings or local_settings());taxonomy=rules()
    requested=settings['device'];device=('cuda:0' if torch.cuda.is_available() else 'cpu') if requested=='auto' else requested
    def run(target):
        paths=[ROOT/settings[k] for k in ['sam_weights','clip_weights']]
        state=tuple((p.stat().st_size,p.stat().st_mtime_ns) if p.exists() else (0,0) for p in paths)
        with _creation_lock:
            engine=_engine(json.dumps(settings,sort_keys=True),json.dumps(taxonomy,sort_keys=True),target,state)
        return engine.infer(source)
    try:
        return run(device)
    except RuntimeError as exc:
        if device.startswith('cuda') and any(x in str(exc).lower() for x in ['cuda','cudnn','out of memory']):
            _engine.cache_clear();torch.cuda.empty_cache()
            result=run('cpu');result.metadata['fallback']='CUDA 运行失败，已在 CPU 重试。';return result
        raise
