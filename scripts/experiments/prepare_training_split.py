"""训练前固定人工视觉复核清单；按作者和感知近重复连通分组，旧测试永久隔离。"""
import argparse,hashlib,json,sys
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from garbage_vision.config import ROOT,rules,weight_hash
from garbage_vision.images import decode_image

# 这些名单在任何本轮模型预测之前，由原图、作者说明和既有分类规则确定。
# 正在使用的设施/化学容器、无可见主体、混合未穷尽标签、绘图等不纳入监督标签。
ACCEPTED={
 'plastic bottle':[133213919,11501794,135247696,30863420,1853534,150241014],
 'glass bottle':[178939620,178911721,157208854,62068994,49357728,73951469,136125361,139883279,56110122,12618853,168301699,89110886,72168911,19812967,56878983,18593073,78687559,190535833],
 'metal can':[48583266,75430479,23153953,71285002,183068752],
 'cardboard box':[34194155,3824115,3715945,31309987,196595505,4254668,15673462,15708973,51928285,73868941,14576332,14576320,98972328,111519753,143847970,95832866],
 'banana peel':[153623717],
 'apple core':[69288328],
 'food waste':[38813889,35653484,36853788,36853662,33255950,137972888,105181640],
 'cigarette butt':[148585374,100575469,197020093,199659603,174089462],
 'compact fluorescent lamp':[9994042,31101011],
 'fluorescent tube':[27242152,20447494],
 'battery':[209635,195759658,161583411,177957290,177957295,178634687],
 'LED light bulb':[11771871,101149484,101149487,29428919,14923187,124715712,65946910,19371511,42447357],
 'incandescent light bulb':[115645860,17848122,116164795,45320258,84104293,75939774,50998026],
 'tree leaves':[79884928,83728919],
 'metal tool':[130215595,130215589],
 'container':[48339831],
 'background':[130216008,130216012,130215583,154679696,85152572,4348322,97977190,112295558,69735323,147251547,147251551,129795561],
}
DEV_EXCLUDE={179028310:'瓶内有疑似烟蒂，不将多物品整图作单物品监督',
 10578610:'混有瓶罐纸杯，旧粗标签不适合细粒度监督',56167128:'动物为画面主体，食物只占很小区域'}

def read(name):return json.loads((ROOT/'data/manifests'/name).read_text(encoding='utf-8'))

def near(a,b):
    return a['sha256']==b['sha256'] or (int(a['dhash'],16)^int(b['dhash'],16)).bit_count()<=5

def build(replace_draft=False):
    folder=ROOT/'data/manifests'
    if (ROOT/'evidence/v0.6.0/local-training/protocol-freeze.json').exists():raise ValueError('已经冻结，不覆盖。')
    if (folder/'training_test_v06.json').exists() and not replace_draft:raise ValueError('已有草案，需显式 --replace-draft；只允许训练冻结前。')
    olddev=read('quality_dev.json');oldtests=read('test.json')+read('quality_test.json')
    allrows={r['id']:r for n in ['quality_candidates.json','quality_supplement.json','training_candidates_v06.json','training_supplement_v06.json'] for r in read(n)}
    selected=[];audit=[];mapping={r['label']:r['category'] for r in rules()['items']}
    for r in olddev:
        n=int(r['id'].split('-')[1])
        if n in DEV_EXCLUDE:audit.append({'id':r['id'],'reason':DEV_EXCLUDE[n]});continue
        label='fluorescent tube' if n==80933087 else 'vegetable peels' if n==185140035 else r['support_label']
        selected.append({**r,'training_label':label,'prior_development':True})
    for label,ids in ACCEPTED.items():
        for n in ids:selected.append({**allrows['commons-'+str(n)],'training_label':label,'prior_development':False})
    assert len({r['id'] for r in selected})==len(selected)
    oldauthors={r['author'].strip() for r in oldtests if r['author'].strip()}
    clean=[]
    for r in selected:
        if r['author'].strip() in oldauthors or any(near(r,t) for t in oldtests):
            audit.append({'id':r['id'],'reason':'与历史测试作者或图像近重复，排除'});continue
        source=decode_image((ROOT/r['path']).read_bytes())
        if source.source_sha256!=r['sha256']:raise ValueError('原图哈希变化')
        category=mapping.get(r['training_label'])
        r.update(categories=[category] if category else [],background='未按背景复杂度分层',
            review_status='accepted',annotator='Commons 作者元数据 + Codex 逐图视觉复核，非独立真人标注',
            review_note='主要物品假定已决定丢弃；背景设施不计。标签在本轮预测前固定。整图监督，不提供框真值。')
        clean.append(r)
    # 并查集合并同作者和近重复，不允许一个拍摄系列分散到训练、验证、测试。
    parents=list(range(len(clean)))
    def find(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    for i,a in enumerate(clean):
        for j,b in enumerate(clean[:i]):
            same_author=bool(a['author'].strip()) and a['author'].strip()==b['author'].strip()
            if same_author or near(a,b):parents[find(i)]=find(j)
    groups=defaultdict(list)
    for i,r in enumerate(clean):groups[find(i)].append(r)
    assignments={};counts={s:Counter() for s in ['train','validation','test']}
    targets={'test':{'recyclable':8,'kitchen':4,'other':2,'hazardous':2,'empty':8},
             'validation':{'recyclable':6,'kitchen':3,'other':1,'hazardous':1,'empty':6}}
    groups=sorted(groups.values(),key=lambda g:hashlib.sha256(('20261019|'+','.join(sorted(r['id'] for r in g))).encode()).hexdigest())
    for group in groups:
        group_id=hashlib.sha256(','.join(sorted(r['id'] for r in group)).encode()).hexdigest()[:16]
        if any(r['id']=='commons-5559269' for r in group):split='validation'
        elif any(r['prior_development'] for r in group):split='train'
        else:
            bucket=Counter((r['categories'] or ['empty'])[0] for r in group).most_common(1)[0][0]
            split=next((s for s in ['test','validation'] if counts[s][bucket]<targets[s][bucket]),'train')
        for r in group:
            r.update(split=split,training_group=group_id)
            counts[split].update(r['categories'] or ['empty']);assignments[r['id']]=r
    for split in counts:
        rows=sorted((r for r in clean if r['split']==split),key=lambda r:r['id'])
        (folder/f'training_{split}_v06.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in allrows.values():
        if r['id'] not in assignments and not any(a['id']==r['id'] for a in audit):
            audit.append({'id':r['id'],'reason':'未纳入本轮：候选视觉复核后不满足清晰主体/用途/完整标签条件，或同源冗余；不根据预测筛选'})
    report={'created_at_utc':datetime.now(timezone.utc).isoformat(),'counts':counts,
            'groups':{s:len({r['training_group'] for r in clean if r['split']==s}) for s in counts},
            'labels':{s:dict(Counter(r['training_label'] for r in clean if r['split']==s)) for s in counts},
            'excluded':audit,'historical_test_images':len(oldtests),'near_duplicate_metric':'64-bit dHash XOR Hamming <= 5',
            'limits':'small nonrepresentative convenience sample; author grouping is conservative but does not prove scene independence; no bounding-box annotations'}
    (folder/'training_split_audit_v06.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='excluded'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--replace-draft',action='store_true');build(parser.parse_args().replace_draft)
