"""真实HTTP本地模型检查；默认不发送外部API请求，不用模拟替代推理。"""
import argparse
from datetime import datetime
import hashlib
from io import BytesIO
import json
import sys
import time
from pathlib import Path
from uuid import uuid4
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from garbage_vision.images import decode_image
from garbage_vision.service_client import request


def verify(paths,out,resume=False):
    out.mkdir(parents=True,exist_ok=True)
    progress_path=out/'verification-progress.json'
    progress=json.loads(progress_path.read_text(encoding='utf-8')) if resume else {'tasks':[]}
    evidence={'verification':'real HTTP + original local model; no paid API calls','tasks':[]}
    for index,path in enumerate(paths):
        data=path.read_bytes();source=decode_image(data);key=str(uuid4());start=time.perf_counter()
        if index<len(progress['tasks']):
            saved=progress['tasks'][index]
            assert saved['source_sha256']==source.source_sha256, '恢复记录与当前输入不一致'
            task_id,key=saved['task_id'],saved['request_key']
        else:
            response=request('POST','/v1/tasks',files={'file':(path.name,data)},
                             data={'include_api':'false'},headers={'Idempotency-Key':key})
            task_id=response.json()['id']
            progress['tasks'].append({'task_id':task_id,'request_key':key,'source_sha256':source.source_sha256})
            progress_path.write_text(json.dumps(progress,indent=2),encoding='utf-8')
        while time.perf_counter()-start<600:
            task=request('GET','/v1/tasks/'+task_id).json()
            if task['status'] not in {'queued','running'}:break
            time.sleep(.5)
        assert task['status']=='succeeded',task.get('error') or task['status']
        assert task['source_sha256']==hashlib.sha256(data).hexdigest()
        # PNG压缩字节随平台库变化；核对服务器PNG哈希及解码像素，不能要求客户端重编码字节相同。
        server_png=request('GET',f'/v1/tasks/{task_id}/image').content
        assert hashlib.sha256(server_png).hexdigest()==task['image_id']
        with Image.open(BytesIO(server_png)) as returned:
            assert returned.size==source.image.size and returned.convert('RGB').tobytes()==source.image.tobytes()
        result=task['results']['local']
        assert result['image_id']==task['image_id'] and result['source_sha256']==task['source_sha256'] and task['api_status']=='skipped'
        exported=request('GET',f'/v1/tasks/{task_id}/export').json()
        assert exported['task']['results']==task['results']
        annotated=request('GET',f'/v1/tasks/{task_id}/annotated').content
        (out/(task_id+'.json')).write_text(json.dumps(exported,ensure_ascii=False,indent=2),encoding='utf-8')
        (out/(task_id+'-annotated.png')).write_bytes(annotated)
        repeated=request('POST','/v1/tasks',files={'file':(path.name,data)},data={'include_api':'false'},headers={'Idempotency-Key':key}).json()
        assert repeated['id']==task_id and repeated['created'] is False
        evidence['tasks'].append({'task_id':task_id,'sample':path.name,'status':task['status'],
            'device':result['metadata'].get('device'),'verification_seconds':round(time.perf_counter()-start,3),
            'task_elapsed_seconds':round((datetime.fromisoformat(task['updated_at'])-datetime.fromisoformat(task['created_at'])).total_seconds(),3),
            'image_id':task['image_id'],'canonical_pixels_match_client':True,
            'item_count':len(result['items']),'duplicate_submission_reused':True})
        print(json.dumps(evidence['tasks'][-1],ensure_ascii=False),flush=True)
        (out/'summary.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('images',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'.local/stage3-http-check')
    parser.add_argument('--resume',action='store_true',help='显式复用该输出目录中已提交的检查任务，不重复执行模型')
    args=parser.parse_args();verify(args.images,args.output,args.resume)
