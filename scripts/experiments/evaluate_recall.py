"""Select bounded recall candidates on development, then report frozen regressions."""
import argparse,json,sys,subprocess
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from garbage_vision.config import ROOT,weight_hash
from garbage_vision.schema import InferenceResult
from garbage_vision.recall import supplement_regions
from garbage_vision.evaluation import score_records

OUT=ROOT/'evidence/v0.8.0/recall'
OLD=ROOT/'evidence/v0.7.0/detection-training'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(v,f,ensure_ascii=False,indent=2)

def scored(rows,records):
    r=score_records(rows,records);r['exact_count']=sum(x['exact_match'] for x in r['records'])
    r['unknown_false_positive_images']=sum(not x['truth'] and bool(x['predicted']) for x in r['records'])
    return r

def replay(rows,a_dir,b_dir,choice,folder):
    records=[]
    for row in rows:
        a,b=read(a_dir/(row['id']+'.json')),read(b_dir/(row['id']+'.json'))
        r=supplement_regions(InferenceResult.model_validate(b['result']),InferenceResult.model_validate(a['result']),
            margin_min=choice['margin_min'],mode=choice['mode'])
        r.metadata['timing_note']='Replay of genuine archived components; not an end-to-end speed measurement.'
        record={'id':row['id'],'expected_categories':row['categories'],'result':r.model_dump()}
        write(folder/(row['id']+'.json'),record);records.append(record)
    metrics=scored(rows,records);write(folder/'metrics.json',metrics);return metrics

def select():
    rows=read(ROOT/'data/manifests/training_validation_v06.json')
    choices=[{'name':f'{mode}-{margin:.2f}','mode':mode,'margin_min':margin} for mode in ['empty-only','uncovered'] for margin in [.03,.04,.05]]
    files=[ROOT/'garbage_vision/recall.py',Path(__file__),ROOT/'data/manifests/training_validation_v06.json']
    sources=[p for folder in ['baseline','conf-0.15-fallback-true'] for p in (OLD/'validation'/folder).glob('*.json')]
    write(OUT/'protocol-freeze.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),'choices':choices,
        'files':{p.relative_to(ROOT).as_posix():weight_hash(p) for p in files+sources},
        'selection':'Only old 17-image validation now used as development. Max exact count then mean F1 then fewer empty-reference false positives; ties prefer empty-only then larger margin.',
        'regression_gate':'Compare selected candidate once on historical 29 TACO +25 Commons. Must retain detector candidate gains, not reduce baseline category TP or add empty-reference false positives. No per-image routing. Old tests are regression only.',
        'fresh_gate':'New images and labels frozen before inference. Candidate exact/F1 must not decrease vs baseline and prior detector; no new unknown/background false positives or inference errors. These limited images cannot establish full four-class reliability.',
        'promotion':'Only offer experimental mode if gates pass. No automatic production replacement; report optimization before next project phase.'})
    base=read(OLD/'validation/baseline/metrics.json');results=[]
    for c in choices:
        metric=replay(rows,OLD/'validation/baseline',OLD/'validation/conf-0.15-fallback-true',c,OUT/'development'/c['name'])
        results.append({**c,'metrics':metric})
    best=max(results,key=lambda r:(r['metrics']['exact_count'],r['metrics']['mean_per_image_f1'],
        -r['metrics']['unknown_false_positive_images'],r['mode']=='empty-only',r['margin_min']))
    write(OUT/'selection.json',{'baseline':base,'candidates':results,'chosen':best,'selection_data_role':'Reused development, not independent evaluation'})
    print('SELECTED',best['name'],base['exact_count'],'->',best['metrics']['exact_count'])

def regression():
    f=read(OUT/'protocol-freeze.json')
    for name,h in f['files'].items():
        if weight_hash(ROOT/name)!=h:raise ValueError('Frozen source changed: '+name)
    choice=read(OUT/'selection.json')['chosen'];scores={}
    write(OUT/'regression-freeze.json',{'selection_sha256':weight_hash(OUT/'selection.json'),
        'choice':{k:choice[k] for k in ['name','mode','margin_min']}})
    for name,manifest in [('fresh','detection_category_test_v07'),('regression','training_test_v06')]:
        rows=read(ROOT/f'data/manifests/{manifest}.json')
        score=replay(rows,OLD/'test'/name/'baseline',OLD/'test'/name/'candidate',choice,OUT/'regression'/name)
        scores[name]={'baseline':read(OLD/'test'/name/'baseline/metrics.json'),
            'prior_detector':read(OLD/'test'/name/'candidate/metrics.json'),'candidate':score}
        print(name,'baseline',scores[name]['baseline']['exact_count'],'detector',scores[name]['prior_detector']['exact_count'],'recall',score['exact_count'])
    gates={}
    for name,r in scores.items():
        a,b,c=r['baseline'],r['prior_detector'],r['candidate']
        gates[name+'_retains_gains']=c['exact_count']>=max(a['exact_count'],b['exact_count']) and c['mean_per_image_f1']>=max(a['mean_per_image_f1'],b['mean_per_image_f1'])
        gates[name+'_no_category_tp_drop']=all(c['per_category'][k]['tp']>=a['per_category'][k]['tp'] for k in a['per_category'])
        gates[name+'_no_extra_empty_fp']=c['unknown_false_positive_images']<=min(a['unknown_false_positive_images'],b['unknown_false_positive_images'])
    write(OUT/'regression-decision.json',{'gates':gates,'passed':all(gates.values()),'results':scores,
        'scope':'Both groups are reused historical regression data, not fresh test results.'})
    print('GATES',gates)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['select','regression']);a=p.parse_args();globals()[a.stage]()
