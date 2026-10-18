"""SAM 自动分割 + CLIP 区域分类开发实验；无测试集推理。"""
from datetime import datetime, timezone
import json,os,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2]
os.chdir(root);sys.path.insert(0,str(root))
os.environ['YOLO_CONFIG_DIR']=str(root/'.local/ultralytics');os.environ['YOLO_AUTOINSTALL']='false'
import numpy as np
import torch,clip
from PIL import ImageDraw
from ultralytics import SAM
from ultralytics.models.sam.predict import SAM2Predictor
from garbage_vision.images import decode_image
labels=['plastic bottle','glass bottle','metal can','cardboard box','banana peel','apple core','food waste','vegetable peels','cigarette butt','used tissue','compact fluorescent lamp','fluorescent tube','medicine pills','battery','incandescent light bulb','LED light bulb',
        'tree leaves','stone','wood','table','wall','floor','person','animal','container','wire','metal tool','background']
text=clip.tokenize(['a photo of '+x for x in labels]).to('cuda:0')
cl,pre=clip.load(str(root/'weights/ViT-B-32.pt'),device='cuda:0')
with torch.inference_mode():
 tf=cl.encode_text(text).float();tf/=tf.norm(dim=-1,keepdim=True)
class RegionPredictor(SAM2Predictor):
 def generate(self,im,**kwargs):return super().generate(im,points_stride=24,points_batch_size=32,**kwargs)
sam=SAM(str(root/'weights/sam2.1_t.pt'))
rows=json.loads((root/'data/manifests/dev.json').read_text(encoding='utf-8'))
preds=[]
for row in rows:
 if row['id'] not in ['commons-179028310','commons-44824808','commons-79335127','commons-9690809','commons-39198884']:continue
 src=decode_image((root/row['path']).read_bytes());started=time.perf_counter()
 result=sam.predict(src.image,device='0',verbose=False,imgsz=1024,predictor=RegionPredictor,conf=.25,iou=.7)[0]
 boxes=result.boxes.xyxy.cpu().tolist();scores=result.boxes.conf.cpu().tolist()
 candidates=[]
 for box,score in zip(boxes,scores):
  x1,y1,x2,y2=box
  if (x2-x1)*(y2-y1)<80 or min(x2-x1,y2-y1)<5:continue
  # 给分割框留少量背景，避免裁切边缘丢失物品线索。
  pad=.05*max(x2-x1,y2-y1)
  crop=src.image.crop((max(0,x1-pad),max(0,y1-pad),min(src.image.width,x2+pad),min(src.image.height,y2+pad)))
  with torch.inference_mode():
   feature=cl.encode_image(pre(crop).unsqueeze(0).to('cuda:0')).float();feature/=feature.norm(dim=-1,keepdim=True)
   sim=(feature@tf.T)[0];values,inds=sim.topk(2)
  candidates.append(dict(label=labels[int(inds[0])],similarity=float(values[0]),margin=float(values[0]-values[1]),mask_score=score,box=box))
 print(row['id'],'regions',len(boxes),[(x['label'],round(x['similarity'],3),round(x['margin'],3)) for x in candidates],flush=True)
 preds.append(dict(id=row['id'],seconds=time.perf_counter()-started,regions=candidates))
 canvas=src.image.copy();draw=ImageDraw.Draw(canvas)
 for x in candidates:
  if labels.index(x['label'])<16:
   draw.rectangle(x['box'],outline='red',width=3);draw.text(x['box'][:2],x['label'],fill='red')
 out=root/'data/cache/sam-clip';out.mkdir(parents=True,exist_ok=True);canvas.save(out/(row['id']+'.jpg'))
out=root/'evidence/v0.2.0'/('sam-clip-probe-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'));out.mkdir(parents=True,exist_ok=True)
(out/'predictions.json').write_text(json.dumps(dict(labels=labels,predictions=preds),ensure_ascii=False,indent=2),encoding='utf-8')
