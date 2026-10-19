"""真实监督训练 CLIP 分类层、独立验证选择与新测试比较；不调用任何收费 API。

SAM 与图像/文本编码器冻结。以文本向量为起点，梯度更新类别向量，使用 L2 锚定和
预声明的混合强度限制小样本过拟合。只有图像级标签，不能声称训练了检测定位。
"""
import argparse,json,subprocess,sys,time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import numpy as np
import torch
from PIL import Image,ImageOps,ImageEnhance
from compare_encoders import CachedSAM
from garbage_vision.config import ROOT,local_settings,rules,weight_hash,fingerprint
from garbage_vision.experiment import text_hash
from garbage_vision.images import decode_image
from garbage_vision.local import LocalEngine
from garbage_vision.schema import InferenceResult
from garbage_vision.evaluation import score_records

OUT=ROOT/'evidence/v0.6.0/local-training'
PARAMS={'seed':20261019,'epochs':150,'learning_rate':0.01,'temperature':20.0,
        'anchor_strengths':[10.0,100.0],'blend_strengths':[0.25,0.5],
        'augmentations':['original','mirror','brightness_0.9','brightness_1.1']}

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def manifest(split):return read(ROOT/f'data/manifests/training_{split}_v06.json')

def audit_splits(splits,old_tests):
    """在编码/训练之前拒绝标签泄漏、旧测试复用及跨集合近重复。"""
    from prepare_training_split import near
    ids=set();seen=[]
    for split,rows in splits.items():
        for row in rows:
            if row['id'] in ids:raise ValueError('Duplicate image id')
            ids.add(row['id'])
            if row['split']!=split:raise ValueError('Split mismatch')
            for old in old_tests:
                if near(row,old) or (row['author'].strip() and row['author'].strip()==old['author'].strip()):
                    raise ValueError('Historical test leakage')
            for other_split,other in seen:
                if split==other_split:continue
                if near(row,other) or row['training_group']==other['training_group'] or (row['author'].strip() and row['author'].strip()==other['author'].strip()):
                    raise ValueError('Cross-split leakage')
            seen.append((split,row))
    return True

def freeze():
    if (OUT/'protocol-freeze.json').exists():raise ValueError('Do not overwrite freeze')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise ValueError('Commit code/data before freezing')
    splits={s:manifest(s) for s in ['train','validation','test']}
    audit_splits(splits,read(ROOT/'data/manifests/test.json')+read(ROOT/'data/manifests/quality_test.json'))
    files=list((ROOT/'garbage_vision').glob('*.py'))+[ROOT/'config/local_model.json',ROOT/'config/local_texts_v2.json',ROOT/'config/categories.json',Path(__file__),ROOT/'scripts/experiments/compare_encoders.py',ROOT/'scripts/experiments/prepare_training_split.py']
    files += [ROOT/f'data/manifests/training_{s}_v06.json' for s in splits]
    for rows in splits.values():
        for row in rows:
            if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Image hash mismatch')
    write(OUT/'protocol-freeze.json',{'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'settings':local_settings(),'parameters':PARAMS,
        'files':{p.relative_to(ROOT).as_posix():text_hash(p) for p in files},
        'weights':{local_settings()[k]:weight_hash(ROOT/local_settings()[k]) for k in ['clip_weights','sam_weights']},
        'selection':'Validation only. Prefer candidates with no extra unknown/background false positives. Maximize exact-set count, then mean F1; ties prefer stronger anchor then lower blend. If none beats baseline, still test best trained candidate but forbid promotion.',
        'promotion':'Validation eligibility plus test exact-set count strictly improves, mean F1 strictly improves, unknown/background false positives do not increase, every known-category TP does not decrease, and no inference failures.',
        'annotation':'Author metadata and Codex visual review before inference; no independent human verification or box labels.',
        'timing':'Real SAM regions may be reused across heads. Cached timings cannot establish end-to-end speed improvement.',
        'counts':{s:len(rows) for s,rows in splits.items()}})
    print('FROZEN', {s:len(rows) for s,rows in splits.items()},flush=True)

def verify():
    frozen=read(OUT/'protocol-freeze.json')
    if frozen['parameters']!=PARAMS:raise ValueError('Training protocol changed')
    for p,h in frozen['files'].items():
        if text_hash(ROOT/p)!=h:raise ValueError('Frozen source changed: '+p)
    for p,h in frozen['weights'].items():
        if weight_hash(ROOT/p)!=h:raise ValueError('Frozen weight changed: '+p)
    return frozen

def fit_head(features,targets,base,weights,anchor,parameters):
    """优化实际可训练参数；不更新没有监督样本的类别向量，保留开放词表。"""
    import torch.nn.functional as F
    initial=base.detach().clone();delta=torch.nn.Parameter(torch.zeros_like(initial))
    mask=torch.zeros((len(base),1),device=base.device);mask[targets.unique()]=1
    optimizer=torch.optim.Adam([delta],lr=parameters['learning_rate'])
    logs=[]
    for epoch in range(parameters['epochs']+1):
        learned=F.normalize(initial+delta*mask,dim=-1)
        logits=parameters['temperature']*(features@learned.T)
        ce=(F.cross_entropy(logits,targets,reduction='none')*weights).sum()/weights.sum()
        penalty=((learned-initial).square().sum(dim=1)*mask[:,0]).sum()/mask.sum()
        loss=ce+anchor*penalty
        if epoch%10==0 or epoch==parameters['epochs']:
            logs.append({'epoch':epoch,'objective':float(loss.detach()),'cross_entropy':float(ce.detach()),
                         'anchor_penalty':float(penalty.detach()),'training_top1':float((logits.argmax(1)==targets).float().mean())})
        if epoch==parameters['epochs']:break
        optimizer.zero_grad();loss.backward();optimizer.step()
    return learned.detach(),logs

def train():
    frozen=verify()
    if (OUT/'training.json').exists():raise ValueError('Training already recorded')
    torch.manual_seed(PARAMS['seed']);torch.set_num_threads(4)
    engine=LocalEngine(frozen['settings'],rules(),'cuda:0')
    for p in engine.clip.parameters():p.requires_grad_(False)
    rows=manifest('train');vectors=[];targets=[];sample_keys=[];started=time.perf_counter()
    side=int(engine.clip.visual.input_resolution)
    with torch.inference_mode():
        for index,row in enumerate(rows):
            if weight_hash(ROOT/row['path'])!=row['sha256']:raise ValueError('Image changed')
            im=decode_image((ROOT/row['path']).read_bytes()).image
            views=[im,ImageOps.mirror(im),ImageEnhance.Brightness(im).enhance(.9),ImageEnhance.Brightness(im).enhance(1.1)]
            batch=torch.stack([engine.preprocess(ImageOps.pad(v,(side,side),method=Image.Resampling.BICUBIC,color=(127,127,127))) for v in views]).to(engine.device)
            features=engine.clip.encode_image(batch).float();features/=features.norm(dim=-1,keepdim=True)
            vectors.append(features.cpu().numpy());targets.extend([engine.labels.index(row['training_label'])]*len(views))
            sample_keys.extend([(row['training_label'],row['training_group'])]*len(views))
            if index%15==0:print('encoded training',index+1,'/',len(rows),flush=True)
    # 每个标签等总权重；同标签下每个作者/近重复组等权，增强图不算独立样本。
    group_counts=Counter(sample_keys);label_groups=Counter(k[0] for k in group_counts)
    weights=torch.tensor([1/(group_counts[k]*label_groups[k[0]]) for k in sample_keys],device=engine.device)
    x=torch.tensor(np.concatenate(vectors),device=engine.device);y=torch.tensor(targets,device=engine.device)
    base=engine.text_features.detach().clone();artifacts=[];histories={}
    folder=ROOT/'weights/trained-head-v06';folder.mkdir(parents=True,exist_ok=True)
    for anchor in PARAMS['anchor_strengths']:
        learned,logs=fit_head(x,y,base,weights,anchor,PARAMS);histories[str(anchor)]=logs
        for blend in PARAMS['blend_strengths']:
            combined=torch.nn.functional.normalize((1-blend)*base+blend*learned,dim=-1)
            name=f'anchor-{anchor:g}-blend-{blend:g}';path=folder/(name+'.npz')
            if path.exists():raise ValueError('Do not overwrite weight artifact')
            meta={'kind':'supervised-normalized-classifier','anchor':anchor,'blend':blend,'labels':engine.labels,
                  'rules_sha256':fingerprint(rules()),'clip_sha256':engine.weight_hashes[Path(frozen['settings']['clip_weights']).name],
                  'training_manifest_sha256':text_hash(ROOT/'data/manifests/training_train_v06.json'),
                  'base_vectors_sha256':__import__('hashlib').sha256(base.cpu().numpy().tobytes()).hexdigest()}
            np.savez_compressed(path,features=combined.cpu().numpy(),metadata=np.array(json.dumps(meta)))
            artifacts.append({'name':name,'path':path.relative_to(ROOT).as_posix(),'sha256':weight_hash(path),**meta})
        print('trained anchor',anchor,'CE',logs[0]['cross_entropy'],'->',logs[-1]['cross_entropy'],flush=True)
    write(OUT/'training.json',{'completed_at_utc':datetime.now(timezone.utc).isoformat(),'parameters':PARAMS,
        'device':torch.cuda.get_device_name(0),'independent_images':len(rows),'augmented_views':len(y),
        'supervised_labels':len(set(targets)),'trainable_active_parameters':len(set(targets))*base.shape[1],
        'frozen':'SAM2, CLIP image and text encoders; unseen class prototypes unchanged',
        'seconds_excluding_model_load':time.perf_counter()-started,'histories':histories,'artifacts':artifacts})

def load_features(artifact,labels,base):
    """只读取无 pickle 的数值权重；校验顺序、原型与完整文件哈希。"""
    if weight_hash(ROOT/artifact['path'])!=artifact['sha256']:raise ValueError('Classifier weight hash mismatch')
    with np.load(ROOT/artifact['path'],allow_pickle=False) as data:
        meta=json.loads(str(data['metadata']));features=data['features'].copy()
    if meta['labels']!=labels or features.shape!=tuple(base.shape):raise ValueError('Classifier label/shape mismatch')
    if meta['rules_sha256']!=fingerprint(rules()):raise ValueError('Classifier taxonomy changed')
    if meta['base_vectors_sha256']!=__import__('hashlib').sha256(base.cpu().numpy().tobytes()).hexdigest():raise ValueError('Base prototypes changed')
    if not np.isfinite(features).all() or not np.allclose(np.linalg.norm(features,axis=1),1,atol=1e-4):raise ValueError('Invalid normalized classifier')
    return torch.from_numpy(features).to(base.device)

def run_predictions(split,name,engine,artifact=None):
    out=OUT/split/name;out.mkdir(parents=True,exist_ok=True);rows=manifest(split);records=[]
    for row in rows:
        path=out/(row['id']+'.json')
        if path.exists():records.append(read(path));continue
        source=decode_image((ROOT/row['path']).read_bytes())
        if source.source_sha256!=row['sha256']:raise ValueError('Image changed')
        try:
            result=engine.infer(source)
            if artifact:
                result.model+=' + supervised classifier'
                result.metadata['experimental_classifier']={'name':name,'sha256':artifact['sha256']}
                result.metadata['score_note']='与监督训练后归一化分类向量的余弦相似度，不是概率；SAM 未训练。'
        except Exception as exc:
            result=InferenceResult(image_id=source.image_id,source_sha256=source.source_sha256,image_size=source.image.size,
                                   method='local',model=name,status='error',error=type(exc).__name__+': '+str(exc))
        record={'id':row['id'],'expected_categories':row['categories'],'result':result.model_dump()}
        records.append(record);write(path,record)
        print(split,name,row['id'],row['categories'],sorted(result.categories),result.status,flush=True)
    report=score_records(rows,records)
    report['unknown_false_positive_images']=sum(bool(d['predicted']) for d in report['records'] if not d['truth'])
    report['exact_count']=sum(d['exact_match'] for d in report['records'])
    write(out/'scores.json',report);return report

def validate():
    frozen=verify()
    if (OUT/'selection.json').exists():raise ValueError('Validation already selected')
    training=read(OUT/'training.json');engine=LocalEngine(frozen['settings'],rules(),'cuda:0');engine.sam=CachedSAM(engine.sam,frozen['settings'])
    base=engine.text_features.detach().clone();baseline=run_predictions('validation','baseline',engine);candidates=[]
    for artifact in training['artifacts']:
        engine.text_features=load_features(artifact,engine.labels,base)
        score=run_predictions('validation',artifact['name'],engine,artifact)
        candidates.append({'artifact':artifact,'exact_count':score['exact_count'],'mean_per_image_f1':score['mean_per_image_f1'],
                           'unknown_false_positive_images':score['unknown_false_positive_images'],'failure_rate':score['failure_rate']})
    pool=[c for c in candidates if c['unknown_false_positive_images']<=baseline['unknown_false_positive_images'] and c['failure_rate']==0] or candidates
    chosen=max(pool,key=lambda c:(c['exact_count'],c['mean_per_image_f1'],c['artifact']['anchor'],-c['artifact']['blend']))
    eligible=chosen['exact_count']>baseline['exact_count'] and chosen['mean_per_image_f1']>baseline['mean_per_image_f1'] and chosen['unknown_false_positive_images']<=baseline['unknown_false_positive_images'] and chosen['failure_rate']==0
    write(OUT/'selection.json',{'selected_at_utc':datetime.now(timezone.utc).isoformat(),'chosen':chosen,'eligible_for_promotion':eligible,
        'validation_baseline':{'exact_count':baseline['exact_count'],'mean_per_image_f1':baseline['mean_per_image_f1'],'unknown_false_positive_images':baseline['unknown_false_positive_images']},
        'candidates':candidates,'test_not_used_for_selection':True})
    print('SELECTED',chosen['artifact']['name'],'eligible',eligible,flush=True)

def test():
    frozen=verify();selection=read(OUT/'selection.json')
    path=OUT/'test-freeze.json'
    current={'selection_sha256':text_hash(OUT/'selection.json'),'test_manifest_sha256':text_hash(ROOT/'data/manifests/training_test_v06.json'),
             'classifier':selection['chosen']['artifact']}
    if path.exists():
        if read(path)!=current:raise ValueError('Holdout freeze changed')
    else:write(path,current)
    engine=LocalEngine(frozen['settings'],rules(),'cuda:0');engine.sam=CachedSAM(engine.sam,frozen['settings']);base=engine.text_features.detach().clone()
    baseline=run_predictions('test','baseline',engine)
    artifact=selection['chosen']['artifact'];engine.text_features=load_features(artifact,engine.labels,base)
    candidate=run_predictions('test',artifact['name'],engine,artifact)
    checks={'validation_improved':selection['eligible_for_promotion'],
        'test_exact_count_improved':candidate['exact_count']>baseline['exact_count'],
        'test_mean_f1_improved':candidate['mean_per_image_f1']>baseline['mean_per_image_f1'],
        'no_additional_unknown_false_positives':candidate['unknown_false_positive_images']<=baseline['unknown_false_positive_images'],
        'no_category_tp_regression':all(candidate['per_category'][c].get('tp',0)>=s.get('tp',0) for c,s in baseline['per_category'].items()),
        'no_inference_failure':baseline['failure_rate']==candidate['failure_rate']==0}
    write(OUT/'decision.json',{'completed_at_utc':datetime.now(timezone.utc).isoformat(),'promote':all(checks.values()),'checks':checks,
        'baseline':{k:baseline[k] for k in ['images','exact_count','mean_per_image_f1','unknown_false_positive_images','failure_rate','per_category']},
        'trained_candidate':{k:candidate[k] for k in ['images','exact_count','mean_per_image_f1','unknown_false_positive_images','failure_rate','per_category']},
        'candidate_name':artifact['name'],'claim_limits':'25 new images; source-group split; small convenience sample, no independent human labels, no mAP or general deployment accuracy claim.'})
    print('DECISION',checks,'promote',all(checks.values()),flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['freeze','train','validate','test']);args=parser.parse_args()
    {'freeze':freeze,'train':train,'validate':validate,'test':test}[args.action]()
