"""第二轮已授权 API 验证：3 张历史失败诊断、4 张开发回归、40 张固定复评，共最多47次。"""
import argparse,json,sys
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings,infer_api,PROMPT_PATH
from garbage_vision.config import ROOT,weight_hash
from garbage_vision.images import decode_image
from garbage_vision.experiment import estimate_cost,write_new_json,text_hash,public_api_config
from garbage_vision.evaluation import score_records


def main():
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['diagnose','development','holdout']);p.add_argument('--confirm-paid-api',action='store_true');args=p.parse_args()
    if not args.confirm_paid_api:raise ValueError('Requires explicit authorization for up to 47 calls / CNY 1.50.')
    root=ROOT/'evidence/v0.5.0/api-quality';root.mkdir(parents=True,exist_ok=True)
    settings=replace(api_settings(),max_attempts=1,max_tokens=2048)
    if settings.problem():raise ValueError(settings.problem())
    if settings.model!='qwen3-vl-plus' or settings.base_url!='https://dashscope.aliyuncs.com/compatible-mode/v1':raise ValueError('Budget verified only for Beijing qwen3-vl-plus.')
    manifest='test' if args.phase=='diagnose' else 'dev' if args.phase=='development' else 'quality_test'
    rows=json.loads((ROOT/f'data/manifests/{manifest}.json').read_text(encoding='utf-8'))
    ids={'diagnose':{'commons-133246916','commons-26750498','commons-18975566'},
         'development':{'commons-179028310','commons-136457085','commons-79335127','commons-9690809'}}
    if args.phase in ids:rows=[r for r in rows if r['id'] in ids[args.phase]]
    out=root/args.phase;out.mkdir(exist_ok=True)
    frozen_path=out/'freeze.json'
    state={'phase':args.phase,'image_ids':[r['id'] for r in rows],'image_hashes':{r['id']:r['sha256'] for r in rows},
           'api_config':public_api_config(settings),'source':{p:text_hash(ROOT/p) for p in ['garbage_vision/api.py','garbage_vision/api_normalization.py','garbage_vision/schema.py',PROMPT_PATH,'config/categories.json']},
           'max_calls_entire_round':47,'budget_entire_round_yuan':1.5,'max_attempts':1}
    if frozen_path.exists():
        if json.loads(frozen_path.read_text(encoding='utf-8'))!=state:raise ValueError('Do not change an in-progress API phase.')
    else:write_new_json(frozen_path,state)
    records=[]
    for row in rows:
        target=out/(row['id']+'.json');marker=out/(row['id']+'.started.json')
        if target.exists():records.append(json.loads(target.read_text(encoding='utf-8')));continue
        if marker.exists():raise ValueError('Unresolved request marker; no automatic resubmission.')
        starts=list(root.glob('*/*.started.json'))
        if len(starts)>=47:raise ValueError('Call limit reached.')
        charged=0
        for previous in starts:
            finished=previous.with_name(previous.name.replace('.started.json','.json'))
            if not finished.exists():raise ValueError('Unresolved prior request; stop to reconcile billing.')
            amount=json.loads(finished.read_text(encoding='utf-8')).get('estimated_cost_yuan')
            if amount is None:raise ValueError('Prior usage unknown; stop to reconcile billing.')
            charged+=amount
        if charged+.05>1.5:raise ValueError('Insufficient remaining authorized budget.')
        raw=ROOT/row['path']
        if weight_hash(raw)!=row['sha256']:raise ValueError('Source changed.')
        source=decode_image(raw.read_bytes())
        write_new_json(marker,{'id':row['id'],'image_id':source.image_id,'started_at_utc':datetime.now(timezone.utc).isoformat(),'max_attempts':1})
        result=infer_api(source,settings)
        record={'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump(),
                'estimated_cost_yuan':estimate_cost(result.metadata.get('usage',{}))}
        write_new_json(target,record);records.append(record)
        print(row['id'],result.status,sorted(result.categories),result.metadata.get('validation_errors',[]),record['estimated_cost_yuan'],flush=True)
        if record['estimated_cost_yuan'] is None:raise ValueError('No returned usage; stop subsequent calls.')
    (out/'predictions.json').write_text(json.dumps({'records':records,'api_config':public_api_config(settings)},ensure_ascii=False,indent=2),encoding='utf-8')
    scores=score_records(rows,records)
    (out/'scores.json').write_text(json.dumps(scores,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',args.phase,scores['mean_per_image_f1'],scores['failure_rate'],flush=True)

if __name__=='__main__':main()
