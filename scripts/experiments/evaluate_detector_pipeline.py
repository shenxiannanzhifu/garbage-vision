"""Evaluate experimental detector -> real SAM masks -> unchanged CLIP classifier.

Only development validation selects thresholds. Production LocalEngine is not
modified. Cached true masks are identified by image, detector and SAM hashes;
cached latency is explicitly not an end-to-end speed claim.
"""
import argparse,hashlib,json,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import torch
from garbage_vision.config import ROOT,local_settings,rules,weight_hash,fingerprint
from garbage_vision.images import decode_image
from garbage_vision.local import LocalEngine
from garbage_vision.evaluation import score_records
from compare_encoders import CachedSAM
from train_detector import OUT,read,write,verify

class DetectorSAM:
    """Keep actual SAM mask scores distinct from detector foreground scores."""
    def __init__(self,sam,weight,settings,threshold=.3):
        from ultralytics import YOLO
        self.sam=sam;self.detector=YOLO(str(weight));self.threshold=threshold
        self.detector_hash=weight_hash(weight)
        self.folder=ROOT/'data/cache/detector-sam'/fingerprint({'detector':self.detector_hash,
            'sam':weight_hash(ROOT/settings['sam_weights']),'imgsz':640,'conf':.15,
            'sam_conf':settings['mask_score_min'],'version':1})[:20]
        self.folder.mkdir(parents=True,exist_ok=True);self.last=[]

    def predict(self,im,**kwargs):
        key=hashlib.sha256(im.tobytes()+str(im.size).encode()).hexdigest();path=self.folder/(key+'.npz')
        if not path.exists():
            det=self.detector.predict(im,imgsz=640,conf=.15,iou=.7,max_det=100,device=kwargs['device'],verbose=False)[0]
            boxes=det.boxes.xyxy.cpu().numpy();conf=det.boxes.conf.cpu().numpy()
            if len(boxes):
                result=self.sam.predict(im,bboxes=boxes.tolist(),**kwargs)[0]
                # SAM retains prompt index as its placeholder class after quality filtering.
                idx=result.boxes.cls.cpu().numpy().astype(int)
                masks=result.masks.data.cpu().numpy().astype(bool) if result.masks is not None else np.empty((0,im.height,im.width),bool)
                np.savez_compressed(path,boxes=result.boxes.xyxy.cpu().numpy(),quality=result.boxes.conf.cpu().numpy(),
                    confidence=conf[idx],masks=masks,detector_boxes=boxes,detector_scores=conf)
            else:
                np.savez_compressed(path,boxes=np.empty((0,4),np.float32),quality=np.empty(0,np.float32),
                    confidence=np.empty(0,np.float32),masks=np.empty((0,im.height,im.width),bool),detector_boxes=boxes,detector_scores=conf)
        with np.load(path) as a:
            use=a['confidence']>=self.threshold;boxes=a['boxes'][use];qualities=a['quality'][use];masks=a['masks'][use]
            self.last=[{'bbox':list(map(float,b)),'detection_confidence':float(c)} for b,c in zip(boxes,a['confidence'][use])]
            return [SimpleNamespace(boxes=SimpleNamespace(xyxy=torch.from_numpy(boxes),conf=torch.from_numpy(qualities)),
                masks=SimpleNamespace(data=torch.from_numpy(masks)))]

def run_rows(engine,rows,folder,detector=None):
    records=[];folder.mkdir(parents=True,exist_ok=True)
    for i,row in enumerate(rows,1):
        path=folder/(row['id']+'.json')
        if path.exists():record=read(path)
        else:
            src=decode_image((ROOT/row['path']).read_bytes());assert src.source_sha256==row['sha256']
            result=engine.infer(src)
            if detector:
                result.model='YOLOv8n waste detector + prompted SAM2.1-tiny + frozen CLIP ViT-B/32'
                result.metadata.update(detector_sha256=detector.detector_hash,detector_threshold=detector.threshold,
                    proposal_method='supervised binary detector -> real SAM box-prompt masks',
                    detector_regions=detector.last,experimental=True,timing_note='Real mask cache; not a full runtime benchmark')
                for item in result.items:
                    if item.bbox:
                        match=next((r for r in detector.last if max(abs(x-y) for x,y in zip(item.bbox,r['bbox']))<.02),None)
                        if match:item.detection_confidence=match['detection_confidence']
            record={'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump()}
            write(path,record)
        records.append(record)
        print(folder.name,i,'/',len(rows),row['id'],flush=True)
    score=score_records(rows,records);score['exact_count']=sum(r['exact_match'] for r in score['records'])
    score['unknown_false_positive_images']=sum(not r['truth'] and bool(r['predicted']) for r in score['records'])
    write(folder/'metrics.json',score);return score

def validation():
    verify();training=read(OUT/'training.json');rows=read(ROOT/'data/manifests/training_validation_v06.json')
    if (OUT/'selection.json').exists():raise ValueError('Selection already frozen')
    settings=local_settings();engine=LocalEngine(settings,rules(),'cuda:0');original=engine.sam
    engine.sam=CachedSAM(original,settings)
    baseline=run_rows(engine,rows,OUT/'validation/baseline')
    detector=DetectorSAM(original,ROOT/training['best_weights'],settings);engine.sam=detector
    candidates=[]
    for threshold in [.15,.30,.50]:
        for fallback in [True,False]:
            detector.threshold=threshold;engine.settings={**settings,'image_fallback':fallback}
            name=f'conf-{threshold:.2f}-fallback-{str(fallback).lower()}'
            metric=run_rows(engine,rows,OUT/'validation'/name,detector)
            candidates.append({'name':name,'threshold':threshold,'image_fallback':fallback,'metrics':metric})
    best=max(candidates,key=lambda c:(c['metrics']['exact_count'],c['metrics']['mean_per_image_f1'],
        -c['metrics']['unknown_false_positive_images'],c['threshold'],not c['image_fallback']))
    eligible=best['metrics']['exact_count']>baseline['exact_count']
    write(OUT/'selection.json',{'baseline':baseline,'candidates':candidates,'chosen':best,'validation_eligible':eligible,
        'best_weights_sha256':training['best_sha256'],'note':'Selected only on reserved validation. Test cannot change candidate.'})
    print('VALIDATION',baseline['exact_count'],'->',best['metrics']['exact_count'],best['name'],flush=True)

def test():
    verify();selection=read(OUT/'selection.json');training=read(OUT/'training.json')
    fresh=ROOT/'data/manifests/detection_category_test_v07.json'
    if not fresh.exists():raise ValueError('Fresh category labels must be reviewed and frozen before test')
    freeze=OUT/'test-freeze.json'
    expected={'selected':selection['chosen']['name'],'selection_sha256':weight_hash(OUT/'selection.json'),
        'test_manifest_sha256':weight_hash(fresh),'weights_sha256':training['best_sha256'],
        'production_settings_sha256':weight_hash(ROOT/'config/local_model.json')}
    if freeze.exists():assert read(freeze)==expected
    else:write(freeze,expected)
    settings=local_settings();engine=LocalEngine(settings,rules(),'cuda:0');original=engine.sam
    groups={'fresh':read(fresh),'regression':read(ROOT/'data/manifests/training_test_v06.json')}
    result={}
    for group,rows in groups.items():
        engine.settings=settings;engine.sam=CachedSAM(original,settings)
        a=run_rows(engine,rows,OUT/'test'/group/'baseline')
        choice=selection['chosen'];engine.settings={**settings,'image_fallback':choice['image_fallback']}
        detector=DetectorSAM(original,ROOT/training['best_weights'],settings,choice['threshold']);engine.sam=detector
        b=run_rows(engine,rows,OUT/'test'/group/'candidate',detector);result[group]={'baseline':a,'candidate':b}
    a,b=result['fresh']['baseline'],result['fresh']['candidate'];c,d=result['regression']['baseline'],result['regression']['candidate']
    gates={'validation_exact_improves':selection['validation_eligible'],
        'fresh_at_least_two_more_exact':b['exact_count']>=a['exact_count']+2,'fresh_mean_f1_improves':b['mean_per_image_f1']>a['mean_per_image_f1'],
        'regression_exact_no_drop':d['exact_count']>=c['exact_count'],'regression_f1_no_drop':d['mean_per_image_f1']>=c['mean_per_image_f1'],
        'regression_category_tp_no_drop':all(d['per_category'][k]['tp']>=c['per_category'][k]['tp'] for k in c['per_category']),
        'unknown_background_no_extra_fp':b['unknown_false_positive_images']<=a['unknown_false_positive_images'] and d['unknown_false_positive_images']<=c['unknown_false_positive_images'],
        'no_inference_failures':b['failure_rate']==d['failure_rate']==0}
    write(OUT/'decision.json',{'gates':gates,'eligible_for_promotion':all(gates.values()),'results':result,
        'action':'Report before next phase. If any gate fails, retain baseline and stop this optimization round.'})
    print('DECISION',gates,flush=True)

def detection_test():
    verify()
    if not (OUT/'test-freeze.json').exists():raise ValueError('Freeze selected pipeline and category labels before any test inference')
    from ultralytics import YOLO
    trained=read(OUT/'training.json');model=YOLO(str(ROOT/trained['best_weights']))
    metrics=model.val(data=str(ROOT/'data/cache/detection-v07/data.yaml'),split='test',imgsz=640,batch=8,workers=0,
        device=0,plots=True,project=str(ROOT/'runs/detection-v07'),name='held-out-test',exist_ok=False)
    write(OUT/'detection-test.json',{'metrics':metrics.results_dict,'weights_sha256':trained['best_sha256'],
        'note':'Binary localization metric only; cannot establish four-category classification improvement.'})

if __name__=='__main__':
    torch.set_num_threads(4)
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['validation','test','detection_test']);a=p.parse_args();globals()[a.stage]()
