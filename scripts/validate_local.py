"""完整开发集真实推理及证据保存；默认只读取 dev，不能用此入口跑测试集调参。"""
import hashlib,json,sys,time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.config import ROOT
from garbage_vision.images import decode_image
from garbage_vision.local import infer_local
from garbage_vision.exports import annotate

def main():
    path=ROOT/'data/manifests/dev.json';rows=json.loads(path.read_text(encoding='utf-8'))
    name='local-dev-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    out=ROOT/'evidence/v0.2.0'/name;out.mkdir(parents=True,exist_ok=False)
    imgs=ROOT/'data/cache'/name;imgs.mkdir(parents=True,exist_ok=True)
    records=[]
    for row in rows:
        src=decode_image((ROOT/row['path']).read_bytes());result=infer_local(src)
        records.append({'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump()})
        (imgs/(row['id']+'.png')).write_bytes(annotate(src,result))
        print(row['id'],row['categories'],sorted(result.categories),len(result.items),round(result.elapsed_seconds,2),flush=True)
    import torch
    evidence={'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'annotator':'来源元数据 + Codex 视觉复核，非独立真人标注',
        'torch':torch.__version__,'gpu_peak_allocated_bytes':torch.cuda.max_memory_allocated() if torch.cuda.is_available() else None,'records':records}
    (out/'predictions.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('saved',len(records),flush=True)

if __name__=='__main__':main()
