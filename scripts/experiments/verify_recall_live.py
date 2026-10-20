"""在 GPU 上重新运行原图，验证补漏实现；历史案例回归，不宣称新独立测试。"""
import json,sys,time
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parent)]
import torch
from garbage_vision.config import ROOT,local_settings,rules,weight_hash
from garbage_vision.local import LocalEngine
from garbage_vision.images import decode_image
from garbage_vision.recall import supplement_regions
from garbage_vision.evaluation import score_records
from evaluate_detector_pipeline import DetectorSAM

OUT=ROOT/'evidence/v0.8.0/recall/live'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)

def main():
    torch.set_num_threads(4)
    ids=['commons-36853788','commons-23153953','taco-0685','taco-0309']
    allrows={r['id']:r for name in ['training_validation_v06','training_test_v06','detection_category_test_v07']
             for r in read(ROOT/f'data/manifests/{name}.json')}
    rows=[allrows[k] for k in ids]
    choice=read(OUT.parent/'selection.json')['chosen']
    weight=ROOT/read(ROOT/'evidence/v0.7.0/detection-training/training.json')['best_weights']
    write(OUT/'freeze.json',{'ids':ids,'images':{r['id']:r['sha256'] for r in rows},
        'selection_sha256':weight_hash(OUT.parent/'selection.json'),'weights_sha256':weight_hash(weight),
        'purpose':'Fresh GPU execution of historical cases, no archived segmentation reused; not unseen accuracy.'})
    settings=local_settings();base=LocalEngine(settings,rules(),'cuda:0')
    candidate=LocalEngine(settings,rules(),'cuda:0')
    detector=DetectorSAM(candidate.sam,weight,settings,.15)
    # Unique folder must start empty; writes are evidence cache for this run only.
    detector.folder=ROOT/'data/cache/recall-live-v08'
    if detector.folder.exists():raise ValueError('Live cache already exists; do not silently replay')
    detector.folder.mkdir(parents=True);candidate.sam=detector
    records={k:[] for k in ['baseline','detector','recall']}
    for row in rows:
        src=decode_image((ROOT/row['path']).read_bytes());assert src.source_sha256==row['sha256']
        started=time.perf_counter();a=base.infer(src);b=candidate.infer(src)
        b.model='YOLOv8n + prompted SAM2 + CLIP';b.metadata.update(detector_sha256=detector.detector_hash,detector_regions=detector.last)
        c=supplement_regions(b,a,margin_min=choice['margin_min'],mode=choice['mode'])
        c.metadata['live_pair_wall_seconds']=time.perf_counter()-started
        for label,res in [('baseline',a),('detector',b),('recall',c)]:
            entry={'id':row['id'],'expected_categories':row['categories'],'result':res.model_dump()}
            write(OUT/label/(row['id']+'.json'),entry);records[label].append(entry)
        print(row['id'],'truth',row['categories'],'baseline',sorted(a.categories),'detector',sorted(b.categories),'recall',sorted(c.categories),flush=True)
    write(OUT/'metrics.json',{k:score_records(rows,v) for k,v in records.items()})
    print('LIVE GPU VERIFICATION COMPLETE',flush=True)

if __name__=='__main__':main()
