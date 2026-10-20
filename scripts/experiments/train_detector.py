"""One bounded supervised YOLOv8n experiment. Production settings stay untouched."""
import argparse,hashlib,json,os,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from garbage_vision.config import ROOT,local_settings,weight_hash

OUT=ROOT/'evidence/v0.7.0/detection-training'
PARAMS={'epochs':60,'patience':12,'imgsz':640,'batch':8,'workers':0,'seed':20261019,
    'optimizer':'AdamW','lr0':0.001,'lrf':0.01,'weight_decay':0.0005,
    'warmup_epochs':3,'close_mosaic':10,'mosaic':1.0,'mixup':0.0,'degrees':10.0,
    'translate':0.1,'scale':0.5,'fliplr':0.5,'flipud':0.0,'amp':False,
    'deterministic':True,'pretrained':True,'device':0,'plots':True,'save':True}

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def files():
    return [Path(__file__),ROOT/'scripts/experiments/prepare_detection_data.py',ROOT/'scripts/experiments/evaluate_detector_pipeline.py',
        ROOT/'garbage_vision/local.py',ROOT/'config/local_model.json',ROOT/'config/categories.json',ROOT/'config/local_texts_v2.json']+[
        ROOT/f'data/manifests/detection_{s}_v07.json' for s in ['train','validation','test']]+[
        ROOT/'data/manifests/commons_detection_annotations_v07.json']

def freeze():
    if (OUT/'protocol-freeze.json').exists():raise ValueError('Protocol already frozen')
    splits={s:read(ROOT/f'data/manifests/detection_{s}_v07.json') for s in ['train','validation','test']}
    seen=set()
    for split,rows in splits.items():
        for r in rows:
            assert r['id'] not in seen and r['split']==split;seen.add(r['id'])
            assert weight_hash(ROOT/r['path'])==r['sha256']
    initial=ROOT/'data/cache/taco-source/yolov8n.pt'
    assert weight_hash(initial)=='31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95'
    write(OUT/'protocol-freeze.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'files':{p.relative_to(ROOT).as_posix():weight_hash(p) for p in files()},
        'initial_weight_sha256':weight_hash(initial),'parameters':PARAMS,'baseline_settings':local_settings(),
        'counts':{s:len(r) for s,r in splits.items()},
        'task':'All manually annotated waste instances -> binary waste-object detection; real prompted SAM -> frozen CLIP disposal classifier.',
        'selection':'Best detector epoch uses only detection validation mAP50-95. Pipeline selects conf 0.15/0.30/0.50 and image_fallback true/false on 17 reserved Commons validation images only. Maximize exact-set count, then F1, then fewer unknown/background false positives; ties prefer higher detector confidence and no whole-image fallback.',
        'fresh_evaluation':'All held-out TACO images for binary detection; a separately visually reviewed subset for category-set scoring, frozen before any holdout inference. Historical 25 Commons tests are regression only, not fresh independent data.',
        'promotion':'Reserved Commons validation exact count must improve; fresh reviewed TACO category exact count and mean F1 must both improve (at least 2 additional exact images); historical Commons 25 exact count/F1 and every category TP must not decrease; no extra unknown/background false-positive images or inference failures. Detection mAP alone cannot qualify. Otherwise stop and retain production baseline.',
        'scope_limits':'Convenience sample; batch is not guaranteed photographer separation. TACO lacks fluorescent/medicine categories and has very few food examples. This is a bounded pilot, not proof of production readiness.',
        'stop':'After this one training run and one validation selection/holdout comparison, if gates fail, stop without another optimization route or paid API experiment.'})
    print('PROTOCOL FROZEN',flush=True)

def verify():
    p=read(OUT/'protocol-freeze.json');assert p['parameters']==PARAMS
    for name,h in p['files'].items():
        if weight_hash(ROOT/name)!=h:raise ValueError('Frozen file changed: '+name)
    return p

def train():
    frozen=verify()
    if (OUT/'training.json').exists():raise ValueError('Training evidence already exists')
    os.environ['YOLO_CONFIG_DIR']=str(ROOT/'.local/ultralytics');os.environ['YOLO_AUTOINSTALL']='false'
    import torch
    from ultralytics import YOLO
    torch.set_num_threads(4)
    model=YOLO(str(ROOT/'data/cache/taco-source/yolov8n.pt'))
    start=time.perf_counter()
    model.train(data=str(ROOT/'data/cache/detection-v07/data.yaml'),project=str(ROOT/'runs/detection-v07'),
                name='binary-waste',exist_ok=False,**PARAMS)
    folder=Path(model.trainer.save_dir);best=folder/'weights/best.pt'
    import shutil
    OUT.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(folder/'results.csv',OUT/'training-curves.csv')
    shutil.copyfile(folder/'args.yaml',OUT/'training-args.yaml')
    for name in ['results.png','confusion_matrix_normalized.png']:
        if (folder/name).exists():shutil.copyfile(folder/name,OUT/name)
    write(OUT/'training.json',{'elapsed_seconds':time.perf_counter()-start,'device':torch.cuda.get_device_name(0),
        'torch':torch.__version__,'best_weights':best.relative_to(ROOT).as_posix(),'best_sha256':weight_hash(best),
        'initial_sha256':frozen['initial_weight_sha256'],'actual_epochs':int(model.trainer.epoch)+1,
        'trainable_parameters':sum(p.numel() for p in model.model.parameters()),
        'note':'Supervised detector weights updated using real bounding boxes; SAM and CLIP remain frozen.'})
    print('TRAINING COMPLETE',json.dumps(read(OUT/'training.json')),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['freeze','train']);a=p.parse_args();globals()[a.stage]()
