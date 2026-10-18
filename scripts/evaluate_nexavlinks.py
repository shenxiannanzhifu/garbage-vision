"""在同一冻结40图上复评Astra；开始标记防重发，NEX预算按保守费率逐次核算。"""
import argparse,json,subprocess,sys
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings,infer_api,PROMPT_PATH
from garbage_vision.config import ROOT,weight_hash
from garbage_vision.evaluation import score_records
from garbage_vision.experiment import public_api_config,text_hash,write_new_json
from garbage_vision.images import decode_image
from scripts.nexavlinks_trial import reservation_nex,estimate_nex,PRICE_SOURCE

DIRECTORY=ROOT/'evidence/v0.5.0/astra-holdout'
LOCAL=ROOT/'evidence/v0.5.0/quality-holdout'


def source_paths():
    return list((ROOT/'garbage_vision').glob('*.py'))+[ROOT/PROMPT_PATH,ROOT/'config/categories.json',
        ROOT/'scripts/evaluate_nexavlinks.py',ROOT/'scripts/nexavlinks_trial.py']


def prepare():
    if DIRECTORY.exists():raise ValueError('Do not replace an existing evaluation.')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('Commit before freezing.')
    local=json.loads((LOCAL/'freeze.json').read_text(encoding='utf-8'))
    candidates=json.loads((LOCAL/'candidate/predictions.json').read_text(encoding='utf-8'))['records']
    rows=local['images']
    assert len(rows)==len(candidates)==40
    by_id={r['id']:r['result'] for r in candidates}
    for row in rows:
        if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Image changed.')
        source=decode_image((ROOT/row['path']).read_bytes())
        if by_id[row['id']]['image_id']!=source.image_id:raise ValueError('Local baseline used a different image.')
        row['image_id']=source.image_id
    s=replace(api_settings(),enabled=True,max_attempts=1)
    reservation_nex(decode_image((ROOT/rows[0]['path']).read_bytes()),s)
    frozen={'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'created_at_utc':datetime.now(timezone.utc).isoformat(),'images':rows,'api_config':public_api_config(s),
        'sources':{p.relative_to(ROOT).as_posix():text_hash(p) for p in source_paths()},
        'local_prediction_file':'evidence/v0.5.0/quality-holdout/candidate/predictions.json',
        'local_predictions_sha256':weight_hash(LOCAL/'candidate/predictions.json'),
        'local_freeze_commit':local['git_commit'],'price_source':PRICE_SOURCE,'budget_unit':'NEX',
        'max_calls':40,'max_attempts':1,'promotion_rule':'Do not tune parameters or alter reference labels using this holdout.',
        'reference_note':'Author metadata + pre-inference Codex review, not independently human annotated.',
        'prepared_only_not_authorization':True}
    DIRECTORY.mkdir();write_new_json(DIRECTORY/'freeze.json',frozen)
    print('Frozen 40 original images. No API generation requests made.')


def verify(frozen,s):
    for path,digest in frozen['sources'].items():
        if text_hash(ROOT/path)!=digest:raise ValueError('Source changed after freeze: '+path)
    if public_api_config(s)!=frozen['api_config']:raise ValueError('API configuration changed.')
    if weight_hash(ROOT/frozen['local_prediction_file'])!=frozen['local_predictions_sha256']:
        raise ValueError('Archived local predictions changed.')


def run(budget,authorized):
    if not authorized or not 0<budget<=4:raise ValueError('Explicit approval for up to40 calls and <=4 NEX required.')
    frozen=json.loads((DIRECTORY/'freeze.json').read_text(encoding='utf-8'))
    s=replace(api_settings(),enabled=True,max_attempts=1)
    if s.problem():raise ValueError(s.problem())
    verify(frozen,s);out=DIRECTORY/'api';out.mkdir(exist_ok=True)
    for row in frozen['images']:
        target=out/(row['id']+'.json');marker=out/(row['id']+'.started.json')
        if target.exists():continue
        starts=list(out.glob('*.started.json'))
        if len(starts)>=40:raise ValueError('40 requests already started.')
        spent=0
        for prior in starts:
            done=prior.with_name(prior.name.replace('.started.json','.json'))
            if not done.exists():raise ValueError('Unresolved prior request; reconcile before proceeding.')
            r=json.loads(done.read_text(encoding='utf-8'))
            if r['estimated_cost_nex'] is None:raise ValueError('Unknown prior cost; stop, do not resubmit.')
            if r['result']['status']!='success':raise ValueError('Prior response failed; stop for diagnosis.')
            spent+=r['estimated_cost_nex']
        if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Image changed.')
        source=decode_image((ROOT/row['path']).read_bytes());reserve=reservation_nex(source,s)
        if spent+reserve>budget:raise ValueError('Remaining conservative budget insufficient; preserve partial results.')
        write_new_json(marker,{'id':row['id'],'started_at_utc':datetime.now(timezone.utc).isoformat(),
            'authorized_budget_nex':budget,'authorized_max_calls':40,'reserved_nex':reserve,'attempts':1})
        result=infer_api(source,s);cost=estimate_nex(result.metadata.get('usage',{}))
        write_new_json(target,{'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump(),
            'estimated_cost_nex':cost,'pricing_note':'Conservative higher-group estimate, not actual billed amount.'})
        print(row['id'],result.status,sorted(result.categories),'conservative_nex',cost,flush=True)
        if result.status!='success' or cost is None:raise ValueError('Stopped after failure/unknown usage; no automatic retries.')
    summarize()


def summarize():
    frozen=json.loads((DIRECTORY/'freeze.json').read_text(encoding='utf-8'));out=DIRECTORY/'api'
    records=[json.loads((out/(r['id']+'.json')).read_text(encoding='utf-8')) for r in frozen['images']]
    score=score_records(frozen['images'],records)
    score['known_only']=score_records([r for r in frozen['images'] if r['categories']],
                                    [r for r in records if r['expected_categories']])
    score['unknown_false_positive_images']=sum(any(i['category'] for i in r['result']['items']) for r in records if not r['expected_categories'])
    (out/'predictions.json').write_text(json.dumps({'records':records,'api_config':frozen['api_config'],
        'estimated_cost_nex':sum(r['estimated_cost_nex'] or 0 for r in records)},ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'scores.json').write_text(json.dumps(score,ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',score['images'],'F1',score['mean_per_image_f1'],'exact',score['exact_set_accuracy'],flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','score'])
    p.add_argument('--budget-nex',type=float,default=0);p.add_argument('--confirm-paid-api',action='store_true');a=p.parse_args()
    if a.action=='prepare':prepare()
    elif a.action=='run':run(a.budget_nex,a.confirm_paid_api)
    else:summarize()


if __name__=='__main__':main()
