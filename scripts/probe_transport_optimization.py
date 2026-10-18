"""无损上传候选四图验证：沿用40次/4 NEX总额度，但必须获批改变图片范围。"""
import argparse
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings, infer_api
from garbage_vision.config import ROOT, weight_hash
from garbage_vision.experiment import public_api_config, text_hash, write_new_json
from garbage_vision.images import decode_image
from scripts.openai_trial import TRIAL_IDS
from scripts.nexavlinks_trial import estimate_nex, reservation_nex

DIRECTORY=ROOT/'evidence/v0.5.0/transport-optimization'
BASELINE=ROOT/'evidence/v0.5.0/astra-holdout/api'


def shared_budget(folders):
    count=0;spent=0.0
    for folder in folders:
        for marker in folder.glob('*.started.json'):
            count+=1
            start=json.loads(marker.read_text(encoding='utf-8'))
            done=marker.with_name(marker.name.replace('.started.json','.json'))
            record=json.loads(done.read_text(encoding='utf-8')) if done.exists() else {}
            cost=record.get('estimated_cost_nex')
            # 范围变更授权必须明确包含未知费用请求保留完整预留；不宣称其免费。
            spent+=start['reserved_nex'] if cost is None else cost
    return count,spent


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run'])
    p.add_argument('--confirm-scope-change',action='store_true');p.add_argument('--max-calls',type=int,choices=range(1,5),default=1)
    args=p.parse_args();s=replace(api_settings(),enabled=True,image_transport='lossless',max_attempts=1)
    if s.provider!='nexavlinks' or s.problem():raise ValueError('Configured NexaVLinks credentials required.')
    if not s.proxy_url:raise ValueError('Candidate trial uses previously tested explicit proxy, not direct route.')
    rows=json.loads((ROOT/'data/manifests/dev.json').read_text(encoding='utf-8'))
    rows=[next(r for r in rows if r['id']==key) for key in TRIAL_IDS]
    sources=list((ROOT/'garbage_vision').glob('*.py'))+[ROOT/'prompts/classify_v2.txt',ROOT/'config/categories.json',Path(__file__),ROOT/'scripts/nexavlinks_trial.py']
    freeze=DIRECTORY/'api-freeze.json'
    state={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'api_config':public_api_config(s),'transport_route':'explicit_proxy','sources':{x.relative_to(ROOT).as_posix():text_hash(x) for x in sources},
        'images':rows,'scope':'Up to4 development images, consuming remaining calls from the existing40-call/4-NEX authorization. Requires explicit scope-change approval; preserve full reservations for all prior unknown costs.',
        'max_candidate_calls':4,'shared_max_calls':40,'shared_budget_nex':4,'no_automatic_retries':True}
    if args.action=='prepare':
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('Commit before freezing candidate.')
        write_new_json(freeze,state)
        print('Candidate frozen. No API requests. Scope-change approval still required.');return
    if not args.confirm_scope_change:raise ValueError('Explicit user approval for scope change required.')
    frozen=json.loads(freeze.read_text(encoding='utf-8'))
    for path,digest in frozen['sources'].items():
        if text_hash(ROOT/path)!=digest:raise ValueError('Candidate changed after freeze.')
    if public_api_config(s)!=frozen['api_config']:raise ValueError('Candidate API config changed.')
    out=DIRECTORY/'api';out.mkdir(exist_ok=True)
    for row in rows[:args.max_calls]:
        target=out/(row['id']+'.json');marker=out/(row['id']+'.started.json')
        if target.exists():continue
        starts=list(out.glob('*.started.json'))
        if len(starts)>=args.max_calls:raise ValueError('Candidate call cap reached.')
        for prior in starts:
            done=prior.with_name(prior.name.replace('.started.json','.json'))
            if not done.exists():raise ValueError('Unresolved candidate request; stop.')
            record=json.loads(done.read_text(encoding='utf-8'))
            if record['result']['status']!='success' or record['estimated_cost_nex'] is None:raise ValueError('Prior candidate failed; stop.')
        if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Candidate image changed.')
        source=decode_image((ROOT/row['path']).read_bytes());reserve=reservation_nex(source,s)
        count,spent=shared_budget([BASELINE,out])
        if count>=40 or spent+reserve>4:raise ValueError('Shared authorization exhausted; stop.')
        write_new_json(marker,{'id':row['id'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
            'reserved_nex':reserve,'shared_prior_calls':count,'shared_prior_conservative_nex':spent,
            'shared_max_calls':40,'shared_budget_nex':4,'candidate_max_calls':args.max_calls,'attempts':1})
        result=infer_api(source,s);cost=estimate_nex(result.metadata.get('usage',{}))
        write_new_json(target,{'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump(),'estimated_cost_nex':cost})
        print(row['id'],result.status,sorted(result.categories),'conservative_nex',cost,flush=True)
        if result.status!='success' or cost is None:raise ValueError('Candidate failed; no automatic retry or next call.')


if __name__=='__main__':main()
