"""第二轮在模型推理前固定来源隔离的开发/检查清单；标签来自元数据与 Codex 视觉复核。"""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEV={
 'glass bottle':[68171881], 'metal can':[90150848], 'cardboard box':[125855121],
 'banana peel':[26461093], 'apple core':[1834893], 'cigarette butt':[833960,91300768],
 'used tissue':[97105978], 'compact fluorescent lamp':[52016106,5559269],
 'fluorescent tube':[56666824], 'LED light bulb':[41887069],
 'incandescent light bulb':[242907], 'battery':[97886279,282602],
 'metal tool':[68287941], 'person':[148537788], 'container':[133354163], 'background':[167708642],
}
TEST={
 'recyclable':[128095601,51534756,71363051,131977339,111643306,155630545,138536950,252201],
 'kitchen':[152818746,63297374,5264094,49531104,56853365,88121951,30731906,24364551],
 'other':[95896968,75295601,42032344,114969819,139358689,82983746,101290692],
 'hazardous':[31284758,6215482,27372712,142040226,102772,32438633,90437283,27113623],
 'unknown':[132219783,16022161,102745520,110967099,144928399,87666282,19792555,53453562],
 'mixed':[35832442],
}

def main():
    folder=ROOT/'data/manifests'
    if (folder/'quality_test.json').exists():raise SystemExit('Already frozen; do not overwrite.')
    old=json.loads((folder/'dev.json').read_text(encoding='utf-8'))
    source=json.loads((folder/'quality_candidates.json').read_text(encoding='utf-8'))+json.loads((folder/'quality_supplement.json').read_text(encoding='utf-8'))
    candidates={r['id']:r for r in source}
    taxonomy=json.loads((ROOT/'config/categories.json').read_text(encoding='utf-8'))
    categories={r['label']:r['category'] for r in taxonomy['items']}
    default_labels={'recyclable':'plastic bottle','kitchen':'food waste','other':'cigarette butt','hazardous':'compact fluorescent lamp'}
    dev=[{**r,'support_label':default_labels[r['categories'][0]]} for r in old]
    for label,ids in DEV.items():
        for n in ids:
            r={**candidates['commons-'+str(n)]};category=categories.get(label)
            r.update(support_label=label,categories=[category] if category else [])
            dev.append(r)
    test=[]
    for category,ids in TEST.items():
        for n in ids:
            r={**candidates['commons-'+str(n)]}
            r.update(categories=['kitchen','recyclable'] if category=='mixed' else [] if category=='unknown' else [category],
                     assessment_group=category)
            test.append(r)
    for split,rows in [('quality_dev',dev),('quality_test',test)]:
        for r in rows:
            r.update(split=split,review_status='accepted',reviewed_before_inference=True,
                annotator='Commons 作者元数据 + Codex 视觉复核；非独立真人标注',
                review_note='按主体已决定丢弃的实验条件标注；固定设施、工具、人物和艺术品为背景，无法确认的灯具/电池保留未知。',
                group_id=hashlib.sha256((r['author'].strip() or r['id']).encode()).hexdigest()[:16])
    assert not ({r['group_id'] for r in dev}&{r['group_id'] for r in test})
    removed=[];clean=[]
    for r in test:
        near=[d['id'] for d in dev if r['sha256']==d['sha256'] or (int(r['dhash'],16)^int(d['dhash'],16)).bit_count()<=5]
        if near:removed.append({'id':r['id'],'development_duplicates':near})
        else:clean.append(r)
    for split,rows in [('quality_dev',dev),('quality_test',clean)]:
        (folder/(split+'.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    audit={'created_at_utc':datetime.now(timezone.utc).isoformat(),'dev_images':len(dev),'test_images':len(clean),
        'test_distribution':{k:sum(r['assessment_group']==k for r in clean) for k in TEST},'excluded_near_development':removed,
        'old_test_role':'Original 21-image test remains archived. No image is copied into reference features.',
        'review_scope':'All candidate contact sheets visually inspected before model inference. Missing/unclear subjects, drawings, X-rays and ambiguous mixed scenes excluded before prediction.'}
    (folder/'quality_split_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
