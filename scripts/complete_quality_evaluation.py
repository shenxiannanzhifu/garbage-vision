"""完成未请求的固定测试图；优先类别覆盖，保留失败，须明确批准新限次/中断规则。"""
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
from scripts.nexavlinks_trial import estimate_nex, reservation_nex
from scripts.probe_transport_optimization import shared_budget

DIRECTORY=ROOT/'evidence/v0.5.0/astra-holdout'
CANDIDATE=ROOT/'evidence/v0.5.0/transport-optimization/api'


def interleaved_unsubmitted(rows, completed):
    """只按冻结参考分组交错，不按预测好坏挑图；每张未请求图片恰好一次。"""
    groups={}
    for row in rows:
        if row['id'] not in completed:
            groups.setdefault(row['assessment_group'],[]).append(row)
    output=[]
    while any(groups.values()):
        for key in sorted(groups):
            if groups[key]:output.append(groups[key].pop(0))
    return output


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run'])
    p.add_argument('--confirm-quality-scope',action='store_true');a=p.parse_args()
    original=json.loads((DIRECTORY/'freeze.json').read_text(encoding='utf-8'))
    s=replace(api_settings(),enabled=True,max_attempts=1,image_transport='png')
    if s.problem() or s.provider!='nexavlinks' or not s.proxy_url:raise ValueError('Verified NexaVLinks proxy configuration required.')
    config=public_api_config(s)
    if any(config[k]!=v for k,v in original['api_config'].items()):raise ValueError('Original model/prompt inference settings must be retained.')
    for path in ['prompts/classify_v2.txt','config/categories.json']:
        if text_hash(ROOT/path)!=original['sources'][path]:raise ValueError('Prompt or rules changed.')
    target_freeze=DIRECTORY/'completion-freeze.json';out=DIRECTORY/'api'
    if a.action=='prepare':
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('Commit before preparing.')
        completed={r['id'] for r in original['images'] if (out/(r['id']+'.json')).exists()}
        pending=interleaved_unsubmitted(original['images'],completed)
        count,spent=shared_budget([out,CANDIDATE])
        sources=list((ROOT/'garbage_vision').glob('*.py'))+[Path(__file__),ROOT/'scripts/nexavlinks_trial.py',ROOT/'scripts/probe_transport_optimization.py']
        state={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'api_config':config,'transport_route':'explicit_proxy','images':pending,
            'sources':{p.relative_to(ROOT).as_posix():text_hash(p) for p in sources},
            'existing_shared_calls':count,'existing_conservative_nex':spent,
            'proposed_shared_max_calls':count+len(pending),'shared_budget_nex':4,
            'maximum_new_calls':len(pending),'attempts_per_image':1,
            'failure_policy':'No resend. Reserve full cost for unknown usage and continue next different image. Stop after2 consecutive failures, auth/quota error, unresolved new request, or insufficient budget.',
            'pending_user_approval':True,'test_labels_and_prompt_changed':False,
            'note':'PNG full original pixels, same model/low/high/2048/prompt as original baseline. Source revision adds diagnostic fields; no lossless candidate mixed into holdout.'}
        write_new_json(target_freeze,state)
        print(json.dumps({'new_images':len(pending),'proposed_shared_max_calls':count+len(pending),'existing_budget_accounted_nex':spent,'paid_calls_made':0}));return
    if not a.confirm_quality_scope:raise ValueError('Explicit approval for new count limit and failure policy required.')
    frozen=json.loads(target_freeze.read_text(encoding='utf-8'))
    if frozen['proposed_shared_max_calls']!=42 or frozen['maximum_new_calls']!=22:raise ValueError('Unexpected proposed scope.')
    if config!=frozen['api_config']:raise ValueError('Configuration changed.')
    for path,digest in frozen['sources'].items():
        if text_hash(ROOT/path)!=digest:raise ValueError('Completion source changed.')
    # 已启动的新阶段不能靠再次执行重置连续失败计数。
    failures=0
    for row in frozen['images']:
        target=out/(row['id']+'.json');marker=out/(row['id']+'.started.json')
        if target.exists():
            result=json.loads(target.read_text(encoding='utf-8'))['result']
        else:
            if marker.exists():raise ValueError('Unresolved new request; do not resend.')
            count,spent=shared_budget([out,CANDIDATE])
            if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Image changed.')
            source=decode_image((ROOT/row['path']).read_bytes());reserve=reservation_nex(source,s)
            if count>=42 or spent+reserve>4:raise ValueError('Authorization or budget exhausted.')
            write_new_json(marker,{'id':row['id'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
                'reserved_nex':reserve,'attempts':1,'authorized_shared_max_calls':42,'authorized_budget_nex':4,
                'completion_freeze_sha256':weight_hash(target_freeze),'transport_route':'explicit_proxy',
                'inference_source_commit':frozen['git_commit']})
            inferred=infer_api(source,s);cost=estimate_nex(inferred.metadata.get('usage',{}))
            result=inferred.model_dump()
            write_new_json(target,{'id':row['id'],'expected_categories':row['categories'],'result':result,'estimated_cost_nex':cost,
                'pricing_note':'Higher-group usage estimate; unknown usage retains full original reservation.'})
            print(row['id'],result['status'],sorted(inferred.categories),'conservative_nex',cost,flush=True)
        failures=failures+1 if result['status']!='success' else 0
        if result.get('metadata',{}).get('http_status') in [401,403,429] or failures>=2:
            raise ValueError('Stop: auth/quota problem or2 consecutive failures; no retry.')
    print('Complete40-image records preserved; all failures included.',flush=True)


if __name__=='__main__':main()
