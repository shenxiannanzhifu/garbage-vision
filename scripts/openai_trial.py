"""OpenAI 小规模联调；check 只查访问权限，trial 明确授权后最多四图，不批量复评。"""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings,infer_api,build_payload,PROMPT_PATH
from garbage_vision.config import ROOT,rules,weight_hash
from garbage_vision.images import decode_image
from garbage_vision.experiment import public_api_config,text_hash,write_new_json

PRICE_SOURCE='https://developers.openai.com/api/docs/models/gpt-6-astra'
# 先验证用户反馈过的荧光灯，再验证瓶、厨余、烟头；这些是开发图，不是测试准确率。
TRIAL_IDS=['commons-701056','commons-179028310','commons-136457085','commons-79335127']


def estimated_usd(usage):
    """输入按含缓存写入溢价的上限计，输出包含 reasoning tokens；非账单金额。"""
    i,o=usage.get('input_tokens'),usage.get('output_tokens')
    if any(type(x) is not int or x<0 for x in (i,o)):return None
    if i>272000:raise ValueError('Trial does not support long-context pricing.')
    return (i*12.5+o*50)/1_000_000


def reservation_usd(source,settings):
    """high 最多 2500 patches ×1.2；文本以 UTF-8 字节数保守上界预留。"""
    if settings.model!='gpt-6-astra' or settings.image_detail!='high' or settings.max_tokens>2048:
        raise ValueError('Trial budget verified only for gpt-6-astra, high detail, <=2048 output tokens.')
    prompt=(ROOT/PROMPT_PATH).read_text(encoding='utf-8')+json.dumps(rules(),ensure_ascii=False)
    _,payload=build_payload(source,settings,prompt)
    text_bytes=len((prompt+json.dumps(payload['text'],ensure_ascii=False)).encode('utf-8'))
    return ((text_bytes+512+3001)*12.5+settings.max_tokens*50)/1_000_000


def check_access(settings):
    """只请求模型元信息，不提交图片或文本生成。返回 200 仍需一次生成验证。"""
    try:
        with httpx.Client(timeout=30,trust_env=settings.use_env_proxy,follow_redirects=False) as client:
            response=client.get(settings.base_url+'/models/'+settings.model,
                headers={'Authorization':'Bearer '+settings.key})
        return {'http_status':response.status_code,'model':settings.model,
                'model_visible':response.status_code==200,'generation_verified':False}
    except httpx.RequestError:
        return {'model':settings.model,'model_visible':False,'generation_verified':False,'error':'network_error'}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['check','trial','plan'])
    p.add_argument('--confirm-paid-api',action='store_true')
    p.add_argument('--max-calls',type=int,default=1,choices=range(1,5))
    p.add_argument('--budget-usd',type=float)
    args=p.parse_args();settings=replace(api_settings(),enabled=True,max_attempts=1)
    if settings.provider!='openai':raise ValueError('Select GV_API_PROVIDER=openai first.')
    rows=json.loads((ROOT/'data/manifests/dev.json').read_text(encoding='utf-8'))
    selected=[next(r for r in rows if r['id']==key) for key in TRIAL_IDS]
    if args.action=='plan':
        amounts=[reservation_usd(decode_image((ROOT/r['path']).read_bytes()),settings) for r in selected]
        print(json.dumps({'model':settings.model,'image_ids':TRIAL_IDS,'max_calls':4,
            'reserved_usd_per_image':amounts,'reserved_usd_all_four':sum(amounts),
            'price_source':PRICE_SOURCE,'real_calls_made':0},ensure_ascii=False,indent=2));return
    if settings.problem():raise ValueError(settings.problem())
    if args.action=='check':print(json.dumps(check_access(settings),ensure_ascii=False));return
    if not args.confirm_paid_api or args.budget_usd is None or not 0<args.budget_usd<=1.5:
        raise ValueError('Explicit OpenAI authorization and a budget <= USD 1.50 are required.')
    root=ROOT/'evidence/v0.5.0/openai-trial';root.mkdir(parents=True,exist_ok=True)
    state={'api_config':public_api_config(settings),'images':{r['id']:r['sha256'] for r in selected},
        'source':{str(path.relative_to(ROOT)).replace('\\','/'):text_hash(path)
                  for path in list((ROOT/'garbage_vision').glob('*.py'))+[ROOT/PROMPT_PATH,ROOT/'config/categories.json',Path(__file__)]},
        'max_calls':4,'price_source':PRICE_SOURCE,'no_automatic_retries':True}
    frozen=root/'freeze.json'
    if frozen.exists():
        if json.loads(frozen.read_text(encoding='utf-8'))!=state:raise ValueError('Trial configuration changed; preserve original evidence.')
    else:write_new_json(frozen,state)
    for row in selected[:args.max_calls]:
        target=root/(row['id']+'.json');marker=root/(row['id']+'.started.json')
        if target.exists():continue
        spent=0
        starts=list(root.glob('*.started.json'))
        if len(starts)>=args.max_calls:raise ValueError('Authorized call count reached.')
        for prior in starts:
            finished=prior.with_name(prior.name.replace('.started.json','.json'))
            if not finished.exists():raise ValueError('Unresolved request; reconcile billing before continuing.')
            previous=json.loads(finished.read_text(encoding='utf-8'))
            cost=previous['estimated_cost_usd']
            if cost is None or previous['result']['status']!='success':raise ValueError('Prior call failed or usage unknown; review before continuing.')
            spent+=cost
        if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Input image changed.')
        source=decode_image((ROOT/row['path']).read_bytes());reserve=reservation_usd(source,settings)
        if spent+reserve>args.budget_usd:raise ValueError('Insufficient authorized budget for next request.')
        write_new_json(marker,{'id':row['id'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
            'budget_usd':args.budget_usd,'authorized_max_calls':args.max_calls,'reserved_usd':reserve})
        result=infer_api(source,settings)
        cost=estimated_usd(result.metadata.get('usage',{}))
        write_new_json(target,{'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump(),
            'estimated_cost_usd':cost,'cost_note':'Conservative estimate including cache-write premium; actual bill may differ.'})
        print(row['id'],result.status,sorted(result.categories),'estimated_usd',cost,flush=True)
        if result.status!='success' or cost is None:raise ValueError('Stopped after failure or unknown usage; no automatic retry.')


if __name__=='__main__':main()
