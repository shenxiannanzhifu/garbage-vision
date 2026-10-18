"""只用开发清单比较编码器；缓存真实 SAM 输出，公平复用相同区域以节省重复分割。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import numpy as np
import torch
from garbage_vision.config import ROOT, local_settings, rules, fingerprint
from garbage_vision.images import decode_image
from garbage_vision.local import LocalEngine
from garbage_vision.evaluation import score_records


class CachedSAM:
    """缓存由当前 SAM 权重和参数真实计算的框/掩膜，既不写标签也不生成模拟预测。"""
    def __init__(self,sam,settings):
        self.sam=sam
        frozen={k:v for k,v in settings.items() if not k.startswith(('clip_','visual_','text_','context_')) and k not in ('diagnostic_regions','image_fallback')}
        self.folder=ROOT/'data/cache/encoder-regions'/fingerprint(frozen)[:16]
        self.folder.mkdir(parents=True,exist_ok=True)
    def predict(self,im,**kwargs):
        key=hashlib.sha256(im.tobytes()+str(im.size).encode()).hexdigest()
        path=self.folder/(key+'.npz')
        if not path.exists():
            r=self.sam.predict(im,**kwargs)[0]
            np.savez_compressed(path,boxes=r.boxes.xyxy.cpu().numpy(),scores=r.boxes.conf.cpu().numpy(),
                                masks=r.masks.data.cpu().numpy().astype(bool) if r.masks is not None else np.empty((0,im.height,im.width),dtype=bool))
        with np.load(path) as a:
            return [SimpleNamespace(boxes=SimpleNamespace(xyxy=torch.from_numpy(a['boxes']),conf=torch.from_numpy(a['scores'])),
                                    masks=SimpleNamespace(data=torch.from_numpy(a['masks'])))]


def main():
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=['b32-center','b32-pad','l14-center','l14-pad'],required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--support',action='store_true')
    p.add_argument('--extended-dev',action='store_true')
    p.add_argument('--aliases',action='store_true')
    p.add_argument('--context-weight',type=float,default=0)
    p.add_argument('--image-fallback',action='store_true')
    args=p.parse_args()
    if args.output.exists():raise SystemExit('Do not overwrite evidence.')
    settings=local_settings()
    settings['diagnostic_regions']=True
    settings['clip_resize_mode']='letterbox' if args.variant.endswith('pad') else 'center-crop'
    if args.variant.startswith('l14'):
        settings.update(clip_weights='weights/ViT-L-14.pt',clip_model_name='ViT-L/14',clip_batch_size=8)
    if args.variant.endswith('pad'):
        settings['text_templates']=['a photo of {}.','a close-up photo of {}.','a photo of one or more {}.']
    if args.support:
        settings.update(visual_support='weights/visual-support-'+('l14' if args.variant.startswith('l14') else 'b32')+'.npz',
                        visual_similarity_min=.65,visual_margin_min=.04)
    if args.aliases:settings['text_aliases']='config/local_texts_v2.json'
    if args.context_weight:settings.update(context_weight=args.context_weight,context_padding=.5)
    if args.image_fallback:settings['image_fallback']=True
    args.output.mkdir(parents=True)
    rows=json.loads((ROOT/('data/manifests/quality_dev.json' if args.extended_dev else 'data/manifests/dev.json')).read_text(encoding='utf-8'))
    support_rows=json.loads((ROOT/'data/manifests/quality_dev.json').read_text(encoding='utf-8')) if args.support else []
    groups={r['id']:r['group_id'] for r in support_rows}
    engine=LocalEngine(settings,rules(),'cuda:0');engine.sam=CachedSAM(engine.sam,settings)
    records=[]
    for row in rows:
        if args.support:engine.excluded_support_group=groups[row['id']]
        src=decode_image((ROOT/row['path']).read_bytes());r=engine.infer(src)
        record={'id':row['id'],'expected_categories':row['categories'],'result':r.model_dump()}
        records.append(record)
        (args.output/(row['id']+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(row['id'],row['categories'],sorted(r.categories),len(r.items),flush=True)
    report=score_records(rows,records)
    (args.output/'scores.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.output/'predictions.json').write_text(json.dumps({'variant':args.variant,'config':settings,'records':records,
        'support_evaluation':'leave-one-source-group-out' if args.support else None,
        'timing_note':'SAM regions cached from real inference; elapsed times are NOT full-pipeline benchmarks.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['mean_per_image_f1','exact_set_accuracy','failure_rate']},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
