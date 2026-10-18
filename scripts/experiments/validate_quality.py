"""在新冻结图片上比较旧配置和候选配置；复用真实分割缓存，不作为计时基准。"""
import argparse,json,sys,subprocess
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from compare_encoders import CachedSAM
from garbage_vision.config import ROOT,rules,weight_hash,local_settings
from garbage_vision.experiment import text_hash
from garbage_vision.local import LocalEngine
from garbage_vision.images import decode_image
from garbage_vision.evaluation import score_records


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','baseline','candidate']);p.add_argument('--directory',type=Path,required=True);args=p.parse_args()
    if args.action=='freeze':
        if args.directory.exists():raise ValueError('Do not overwrite evaluation.')
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('Commit before freezing.')
        rows=json.loads((ROOT/'data/manifests/quality_test.json').read_text(encoding='utf-8'))
        sources=list((ROOT/'garbage_vision').glob('*.py'))+list((ROOT/'config').glob('*.json'))+[Path(__file__),ROOT/'scripts/experiments/compare_encoders.py']
        baseline=json.loads((ROOT/'config/local_baseline_v04.json').read_text(encoding='utf-8'))
        candidate=json.loads((ROOT/'config/local_candidate_v05.json').read_text(encoding='utf-8'))
        frozen={'created_at_utc':datetime.now(timezone.utc).isoformat(),'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'baseline':baseline,'candidate':candidate,'images':rows,
            'files':{path.relative_to(ROOT).as_posix():text_hash(path) for path in sources},
            'weights':{baseline[k]:weight_hash(ROOT/baseline[k]) for k in ['sam_weights','clip_weights']},
            'selection_rule':'Candidate selected using development only. No post-test threshold/model selection.',
            'promotion_rule':'Candidate known-image mean F1 improves by at least 0.05, overall exact-set count improves, and unknown false-positive count does not increase.',
            'reference_labels':'Author metadata + Codex visual review before inference; not independently human annotated.',
            'timing_note':'Identical real SAM region predictions may be cached between methods; not a performance benchmark.'}
        for row in rows:
            if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Input hash mismatch.')
        args.directory.mkdir(parents=True)
        (args.directory/'freeze.json').write_text(json.dumps(frozen,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Frozen',len(rows),frozen['git_commit']);return
    frozen=json.loads((args.directory/'freeze.json').read_text(encoding='utf-8'))
    for path,digest in frozen['files'].items():
        if text_hash(ROOT/path)!=digest:raise ValueError('Source changed after freeze: '+path)
    for path,digest in frozen['weights'].items():
        if weight_hash(ROOT/path)!=digest:raise ValueError('Weight changed after freeze.')
    settings=frozen[args.action];engine=LocalEngine(settings,rules(),'cuda:0');engine.sam=CachedSAM(engine.sam,settings)
    out=args.directory/args.action;out.mkdir(exist_ok=True);records=[]
    for row in frozen['images']:
        path=out/(row['id']+'.json')
        if path.exists():records.append(json.loads(path.read_text(encoding='utf-8')));continue
        if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Input hash mismatch.')
        source=decode_image((ROOT/row['path']).read_bytes());r=engine.infer(source)
        record={'id':row['id'],'expected_categories':row['categories'],'result':r.model_dump()};records.append(record)
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(args.action,row['id'],row['categories'],sorted(r.categories),flush=True)
    scores=score_records(frozen['images'],records)
    scores['known_only']=score_records([r for r in frozen['images'] if r['categories']],
                                    [r for r in records if r['expected_categories']])
    scores['unknown_false_positive_images']=sum(bool(r['result']['items']) and any(x['category'] for x in r['result']['items']) for r in records if not r['expected_categories'])
    (out/'scores.json').write_text(json.dumps(scores,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'predictions.json').write_text(json.dumps({'config':settings,'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
    print('DONE',args.action,scores['mean_per_image_f1'],scores['exact_set_accuracy'],'known F1',scores['known_only']['mean_per_image_f1'],'unknown FP',scores['unknown_false_positive_images'],flush=True)

if __name__=='__main__':main()
