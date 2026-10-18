"""NexaVLinks四图小样：按明确NEX预算运行，严禁使用官方美元预算或自动重试。"""
import argparse,json,sys
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings,infer_api,build_payload,PROMPT_PATH
from garbage_vision.config import ROOT,rules,weight_hash
from garbage_vision.images import decode_image
from garbage_vision.experiment import public_api_config,text_hash,write_new_json
from scripts.openai_trial import TRIAL_IDS

PRICE_SOURCE='https://www.nexavlinks.com/modelsmarket/gpt-6-astra'
# 2026-10-18已查看plus密钥分组：Astra专属3.6/18，订阅10/50，按较高价格和写缓存12.5预留。
INPUT_RATE=12.5
OUTPUT_RATE=50


def estimate_nex(usage):
    i,o=usage.get('prompt_tokens'),usage.get('completion_tokens')
    if any(type(x) is not int or x<0 for x in (i,o)):return None
    if i>272000:raise ValueError('Long-context pricing not covered by this trial.')
    return (i*INPUT_RATE+o*OUTPUT_RATE)/1_000_000


def reservation_nex(source,settings):
    if settings.provider!='nexavlinks' or settings.model!='gpt-6-astra' or settings.image_detail!='high' or settings.max_tokens>2048:
        raise ValueError('Trial scope is NexaVLinks gpt-6-astra, high detail, <=2048 output tokens.')
    prompt=(ROOT/PROMPT_PATH).read_text(encoding='utf-8')+json.dumps(rules(),ensure_ascii=False)
    _,payload=build_payload(source,settings,prompt)
    text_bytes=len((prompt+json.dumps(payload['response_format'],ensure_ascii=False)).encode('utf-8'))
    return ((text_bytes+512+3001)*INPUT_RATE+settings.max_tokens*OUTPUT_RATE)/1_000_000


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['plan','trial'])
    p.add_argument('--max-calls',type=int,choices=range(1,5),default=1)
    p.add_argument('--budget-nex',type=float)
    p.add_argument('--confirm-paid-api',action='store_true');args=p.parse_args()
    s=replace(api_settings(),enabled=True,max_attempts=1)
    if s.provider!='nexavlinks':raise ValueError('Select the confirmed NexaVLinks provider.')
    rows=json.loads((ROOT/'data/manifests/dev.json').read_text(encoding='utf-8'))
    rows=[next(r for r in rows if r['id']==key) for key in TRIAL_IDS]
    if args.action=='plan':
        amounts=[reservation_nex(decode_image((ROOT/r['path']).read_bytes()),s) for r in rows]
        print(json.dumps({'provider':s.provider,'model':s.model,'endpoint':s.base_url+'/chat/completions',
            'image_ids':TRIAL_IDS,'max_calls':4,'unit':'NEX','reserved_per_call':amounts,
            'reserved_all_four':sum(amounts),'input_rate_per_million':INPUT_RATE,'output_rate_per_million':OUTPUT_RATE,
            'price_source':PRICE_SOURCE,'generation_calls_made':0},ensure_ascii=False,indent=2));return
    if not args.confirm_paid_api or args.budget_nex is None or not 0<args.budget_nex<=1:
        raise ValueError('Explicit NexaVLinks authorization and NEX budget <=1 required.')
    if s.problem():raise ValueError(s.problem())
    root=ROOT/'evidence/v0.5.0/nexavlinks-trial';root.mkdir(parents=True,exist_ok=True)
    state={'provider':s.provider,'api_config':public_api_config(s),'images':{r['id']:r['sha256'] for r in rows},
        'sources':{p.relative_to(ROOT).as_posix():text_hash(p) for p in list((ROOT/'garbage_vision').glob('*.py'))+
                   [ROOT/PROMPT_PATH,ROOT/'config/categories.json',Path(__file__),ROOT/'scripts/openai_trial.py']},
        'max_calls':4,'budget_unit':'NEX','price_source':PRICE_SOURCE,
        'conservative_rates_per_million':{'input':INPUT_RATE,'output':OUTPUT_RATE},'no_automatic_retries':True}
    freeze=root/'freeze.json'
    if freeze.exists():
        if json.loads(freeze.read_text(encoding='utf-8'))!=state:raise ValueError('Trial source or settings changed; preserve evidence.')
    else:write_new_json(freeze,state)
    for row in rows[:args.max_calls]:
        target=root/(row['id']+'.json');marker=root/(row['id']+'.started.json')
        if target.exists():continue
        starts=list(root.glob('*.started.json'))
        if len(starts)>=args.max_calls:raise ValueError('Authorized call count reached.')
        spent=0
        for prior in starts:
            done=prior.with_name(prior.name.replace('.started.json','.json'))
            if not done.exists():raise ValueError('Unresolved prior request; do not resend.')
            r=json.loads(done.read_text(encoding='utf-8'))
            if r['estimated_cost_nex'] is None or r['result']['status']!='success':raise ValueError('Review prior failure or missing usage before proceeding.')
            spent+=r['estimated_cost_nex']
        if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Image changed.')
        source=decode_image((ROOT/row['path']).read_bytes());reserve=reservation_nex(source,s)
        if spent+reserve>args.budget_nex:raise ValueError('Budget insufficient.')
        write_new_json(marker,{'id':row['id'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
            'budget_nex':args.budget_nex,'max_calls':args.max_calls,'reserved_nex':reserve})
        result=infer_api(source,s);cost=estimate_nex(result.metadata.get('usage',{}))
        write_new_json(target,{'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump(),
            'estimated_cost_nex':cost,'cost_note':'Conservative upper-rate estimate; actual group billing must be checked in gateway logs.'})
        print(row['id'],result.status,sorted(result.categories),'estimated_nex',cost,flush=True)
        if result.status!='success' or cost is None:raise ValueError('Stopped; no automatic retry or next paid request.')


if __name__=='__main__':main()
