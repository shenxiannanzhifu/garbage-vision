"""从固定开发图片构建 CLIP 视觉参考；不修改预训练参数，不读取任何测试图片。"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import clip,numpy as np,torch
from PIL import Image,ImageOps
from garbage_vision.config import ROOT,weight_hash
from garbage_vision.images import decode_image

def main():
    p=argparse.ArgumentParser();p.add_argument('--encoder',choices=['b32','l14'],default='b32');args=p.parse_args()
    path=ROOT/'data/manifests/quality_dev.json';rows=json.loads(path.read_text(encoding='utf-8'))
    weight=ROOT/'weights'/('ViT-B-32.pt' if args.encoder=='b32' else 'ViT-L-14.pt')
    device='cuda:0' if torch.cuda.is_available() else 'cpu'
    model,pre=clip.load(str(weight),device=device);side=int(model.visual.input_resolution)
    features=[];labels=[];groups=[];ids=[]
    with torch.inference_mode():
        for row in rows:
            raw=ROOT/row['path']
            if weight_hash(raw)!=row['sha256']:raise ValueError('Reference image hash changed.')
            image=decode_image(raw.read_bytes()).image
            # 同一原图的完整视图与中心视图属于同一来源组，交叉验证时一起排除。
            views=[ImageOps.pad(image,(side,side),method=Image.Resampling.BICUBIC,color=(127,127,127)),image]
            f=model.encode_image(torch.stack([pre(v) for v in views]).to(device)).float();f/=f.norm(dim=-1,keepdim=True)
            features.extend(f.cpu().numpy());labels.extend([row['support_label']]*len(views));groups.extend([row['group_id']]*len(views));ids.extend([row['id']]*len(views))
    destination=ROOT/f'weights/visual-support-{args.encoder}.npz'
    np.savez_compressed(destination,features=np.asarray(features,dtype=np.float32),labels=np.asarray(labels),groups=np.asarray(groups),ids=np.asarray(ids))
    evidence=ROOT/f'evidence/v0.5.0/visual-support-{args.encoder}.json';evidence.parent.mkdir(parents=True,exist_ok=True)
    evidence.write_text(json.dumps({'method':'frozen CLIP visual reference matching; no gradient training',
        'encoder_sha256':weight_hash(weight),'manifest_sha256':weight_hash(path),'support_sha256':weight_hash(destination),
        'source_images':len(rows),'feature_rows':len(features),'labels':sorted(set(labels)),'source_ids':[r['id'] for r in rows]},indent=2),encoding='utf-8')
    print(destination.name,len(rows),len(features),weight_hash(destination),flush=True)

if __name__=='__main__':main()
