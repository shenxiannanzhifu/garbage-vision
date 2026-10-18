"""开发集基线实验；只读取 dev 清单，不接触测试集预测。"""
from datetime import datetime, timezone
import json,os,sys,time,hashlib,argparse
from pathlib import Path
root=Path(__file__).resolve().parents[2]
os.chdir(root);sys.path.insert(0,str(root))
(root/'.local/ultralytics/Ultralytics').mkdir(parents=True,exist_ok=True)
os.environ['YOLO_CONFIG_DIR']=str(root/'.local/ultralytics')
os.environ['YOLO_AUTOINSTALL']='false'
import torch
from ultralytics import YOLOWorld,YOLOE
from ultralytics.nn.text_model import CLIP
from garbage_vision.images import decode_image
parser=argparse.ArgumentParser();parser.add_argument('--variant',default='s');parser.add_argument('--vocab',default='original');parser.add_argument('--imgsz',type=int,default=960);args=parser.parse_args()
labels=['plastic bottle','glass bottle','metal can','cardboard','banana peel','apple core','food scraps','vegetable peel','cigarette butt','used tissue','compact fluorescent lamp','fluorescent tube','pill','battery']
if args.vocab=='expanded':labels=['plastic bottle','glass bottle','metal can','cardboard box','banana peel','apple core','food waste','vegetable','cigarette','tissue paper','fluorescent light bulb','fluorescent tube','medicine pill','battery','incandescent light bulb','LED light bulb']
if args.vocab=='simple':labels=['bottle','food','cigarette','light bulb','fluorescent lamp','banana','paper','battery']
if args.vocab=='objects':labels=['plastic bottle','glass bottle','aluminum can','cardboard','food','vegetable','fruit','banana peel','cigarette butt','tissue','lightbulb','fluorescent light','fluorescent tube','battery']
started=time.perf_counter()
if args.variant=='e':
    import clip
    class LocalText(torch.nn.Module):
        def __init__(self):
            super().__init__();self.encoder=torch.jit.load(str(root/'weights/mobileclip_blt.ts'),map_location='cuda:0')
        def tokenize(self,text):return clip.tokenize(text).to('cuda:0')
        def encode_text(self,text):return self.encoder(text).float()
    model=YOLOE(str(root/'weights/yoloe-11l-seg.pt')).to('cuda:0')
    model.model.clip_model=LocalText()
    model.set_classes(labels,model.model.get_text_pe(labels,cache_clip_model=True))
else:
    model=YOLOWorld(str(root/f'weights/yolov8{args.variant}-worldv2.pt')).to('cuda:0')
    model.model.clip_model=CLIP(size=str(root/'weights/ViT-B-32.pt'),device=torch.device('cuda:0'))
    model.set_classes(labels)
load_seconds=time.perf_counter()-started
run=f'baseline-{args.variant}-{args.vocab}-{args.imgsz}-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
out=root/'evidence/v0.2.0'/run;out.mkdir(parents=True,exist_ok=True)
predictions=[]
for row in json.loads((root/'data/manifests/dev.json').read_text(encoding='utf-8')):
    src=decode_image((root/row['path']).read_bytes());start=time.perf_counter()
    prediction=model.predict(src.image,imgsz=args.imgsz,conf=.12,iou=.5,agnostic_nms=True,max_det=100,device='0',verbose=False)[0]
    boxes=[dict(label=labels[int(b.cls)],confidence=round(float(b.conf),5),xyxy=[round(float(v),2) for v in b.xyxy[0]]) for b in prediction.boxes]
    predictions.append(dict(id=row['id'],image_id=src.image_id,objects=boxes,elapsed_seconds=time.perf_counter()-start))
    print(row['id'],row['categories'],[(b['label'],b['confidence']) for b in boxes[:8]],flush=True)
    # 标注图仅保存在忽略目录；原始数值证据可以入库。
    annotated=root/'data/cache'/run;annotated.mkdir(parents=True,exist_ok=True)
    prediction.save(filename=str(annotated/(row['id']+'.jpg')))
result=dict(model='yoloe-11l-seg' if args.variant=='e' else f'yolov8{args.variant}-worldv2',labels=labels,conf=.12,imgsz=args.imgsz,iou=.5,agnostic_nms=True,load_seconds=load_seconds,
    dev_sha256=hashlib.sha256((root/'data/manifests/dev.json').read_bytes()).hexdigest(),predictions=predictions)
(out/'predictions.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('completed',len(predictions),'load_seconds',load_seconds,flush=True)
