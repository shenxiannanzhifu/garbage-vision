"""Download a deterministic, batch-separated TACO subset from the official CC BY archive.

All instance boxes become one waste-object class. No TACO class is silently
translated into the project's four disposal categories. Download failures and
near duplicates are recorded before any training or model predictions.
"""
import argparse, concurrent.futures, hashlib, io, json, struct, sys, time, zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from PIL import Image, ImageOps
from garbage_vision.config import ROOT

CACHE=ROOT/'data/cache/taco-source'
OUT=ROOT/'evidence/v0.7.0/detection-training'
URL='https://zenodo.org/api/records/3587843/files/TACO.zip/content'
SEED='20261019-detection-v07'

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(data):return hashlib.sha256(data).hexdigest()

def oriented_taco_image(data,expected):
    im=Image.open(io.BytesIO(data));orientation=im.getexif().get(274,1)
    im=ImageOps.exif_transpose(im)
    if im.size!=tuple(expected):raise ValueError('Oriented image disagrees with annotation dimensions')
    return im.convert('RGB'),orientation

def yolo_box(box,width,height):
    x,y,w,h=map(float,box)
    if min(w,h)<=0 or min(x,y)<-1 or x+w>width+1 or y+h>height+1:
        raise ValueError('Invalid source bounding box')
    x1,y1=max(0,x),max(0,y);x2,y2=min(width,x+w),min(height,y+h)
    return [(x1+x2)/2/width,(y1+y2)/2/height,(x2-x1)/width,(y2-y1)/height]

def dhash(im):
    a=list(im.convert('L').resize((9,8)).getdata());v=0
    for y in range(8):
        for x in range(8):v=(v<<1)|int(a[y*9+x]>a[y*9+x+1])
    return f'{v:016x}'

def download(extend_supported_test=False):
    import httpx
    ann=read(CACHE/'archive-annotations.json');index=read(CACHE/'zip-index.json')
    assert len(ann['images'])==1500 and len(ann['annotations'])==4784
    selections={}
    for split,batches,limit in [('train',range(1,10),700),('validation',range(10,12),100),('test',range(12,16),100)]:
        candidates=[x for x in ann['images'] if int(x['file_name'].split('/')[0].split('_')[1]) in batches]
        selections[split]=sorted(candidates,key=lambda x:sha((SEED+str(x['id'])).encode()))[:limit]
    if extend_supported_test:
        labels={c['id']:c['name'] for c in ann['categories']};by_image={i['id']:set() for i in ann['images']}
        for a in ann['annotations']:by_image[a['image_id']].add(labels[a['category_id']])
        allowed={'Clear plastic bottle','Glass bottle','Food Can','Drink can','Corrugated carton','Food waste','Tissues','Cigarette'}
        existing={r['id'] for r in selections['test']}
        selections['test'] += [r for r in ann['images'] if int(r['file_name'].split('/')[0].split('_')[1])>=12
            and by_image[r['id']] and by_image[r['id']]<=allowed and r['id'] not in existing]
    plan={'seed':SEED,'annotation_sha256':sha((CACHE/'archive-annotations.json').read_bytes()),
          'splits':{k:[x['id'] for x in v] for k,v in selections.items()},'archive_url':URL,
          'license':'CC BY 4.0','doi':'10.5281/zenodo.3587843'}
    plan_path=OUT/('download-plan-supported-extension.json' if extend_supported_test else 'download-plan.json')
    if plan_path.exists():assert read(plan_path)==plan
    else:write(plan_path,plan)
    anns={x['id']:[] for x in ann['images']}
    names={x['id']:x['name'] for x in ann['categories']}
    for a in ann['annotations']:anns[a['image_id']].append(a)
    def one(job):
        split,row=job;image_id=f"taco-{row['id']:04d}"
        meta=CACHE/'downloads'/(image_id+'.json')
        if meta.exists():return read(meta)
        try:
            entry=index['TACO/data/'+row['file_name']]
            start=entry['offset'];size=30+len(('TACO/data/'+row['file_name']).encode())+entry['compressed']+4096
            last=None
            for attempt in range(3):
                try:
                    with httpx.Client(trust_env=False,timeout=90,follow_redirects=True) as client:
                        with client.stream('GET',URL,headers={'Range':f'bytes={start}-{start+size-1}'}) as response:
                            response.raise_for_status()
                            if response.status_code!=206:raise ValueError('Archive server did not honor Range')
                            buf=b''.join(response.iter_bytes())
                    head=struct.unpack('<4s5H3L2H',buf[:30]);assert head[0]==b'PK\x03\x04'
                    pos=30+head[-2]+head[-1];data=buf[pos:pos+entry['compressed']]
                    if entry['method']==8:data=zlib.decompress(data,-15)
                    assert len(data)==entry['size'] and zlib.crc32(data)==entry['crc']
                    break
                except Exception as exc:last=exc;time.sleep(attempt+1)
            else:raise last
            expected=(row['width'],row['height'])
            # 180-degree rotations and square images preserve dimensions; size
            # equality cannot establish orientation. Always apply EXIF first.
            im,orientation=oriented_taco_image(data,expected)
            transform='EXIF transposed before annotation-coordinate normalization'
            im=im.convert('RGB');im.thumbnail((1600,1600),Image.Resampling.LANCZOS)
            path=ROOT/f'data/raw/taco-v07/{image_id}.jpg';path.parent.mkdir(parents=True,exist_ok=True)
            im.save(path,quality=95,subsampling=0)
            boxes=[yolo_box(a['bbox'],*expected) for a in anns[row['id']]]
            result={'id':image_id,'taco_id':row['id'],'path':path.relative_to(ROOT).as_posix(),
                'sha256':sha(path.read_bytes()),'original_sha256':sha(data),'archive_crc32':entry['crc'],
                'dhash':dhash(im),'split':split,'width':im.width,'height':im.height,
                'original_size':list(expected),'original_exif_orientation':orientation,'transform':transform,
                'source_page':'https://zenodo.org/records/3587843','source_file':row['file_name'],
                'flickr_url':row.get('flickr_url'),'license':'CC BY 4.0',
                'author':'Pedro F. Proença and Pedro Simões / TACO contributors',
                'boxes_yolo':boxes,'original_labels':[names[a['category_id']] for a in anns[row['id']]],
                'annotations':[{'id':a['id'],'bbox':a['bbox'],'category':names[a['category_id']]} for a in anns[row['id']]],
                'annotation_scope':'All official litter instances; binary object detection only'}
            write(meta,result);return result
        except Exception as exc:return {'id':image_id,'split':split,'error':type(exc).__name__+': '+str(exc)[:180]}
    jobs=[(split,row) for split,rows in selections.items() for row in rows];results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for n,result in enumerate(pool.map(one,jobs),1):
            results.append(result)
            if n%25==0 or 'error' in result:print(n,'/',len(jobs),result['id'],result.get('error','ok'),flush=True)
    write(OUT/'downloads.json',results)
    print('COMPLETE',len(results),'errors',sum('error' in r for r in results),flush=True)

def finalize():
    rows=read(OUT/'downloads.json');excluded=[r for r in rows if 'error' in r];rows=[r for r in rows if 'error' not in r]
    old=[]
    for name in ['test','quality_test','training_test_v06','training_validation_v06']:
        old+=read(ROOT/f'data/manifests/{name}.json')
    # Preserve holdouts: remove lower-priority duplicates before model inference.
    priority={'test':0,'validation':1,'train':2};kept=[]
    for row in sorted(rows,key=lambda r:(priority[r['split']],r['id'])):
        if row['id'] in {'taco-0925','taco-0942'}:
            excluded.append({'id':row['id'],'split':row['split'],'reason':'Visual review: source boxes use unrotated coordinates despite EXIF=3; exclude inconsistent annotation convention.'})
            continue
        matches=[r['id'] for r in old+kept if (r.get('sha256')==row['sha256'] or
            (r.get('dhash') and (int(r['dhash'],16)^int(row['dhash'],16)).bit_count()<=4))]
        if matches:excluded.append({'id':row['id'],'split':row['split'],'reason':'exact/dhash<=4 overlap','matches':matches})
        else:kept.append(row)
    supplement=ROOT/'data/manifests/commons_detection_annotations_v07.json'
    if not supplement.exists():raise ValueError('Reviewed training supplements are required')
    # Agent-provided schema is explicitly normalized by root before this stage.
    extra=read(supplement)
    if isinstance(extra,dict):extra=extra['images']
    train_sources={r['id']:r for r in read(ROOT/'data/manifests/training_train_v06.json')}
    for x in extra:
        if x.get('review_status')!='accepted':continue
        src=train_sources[x['id']];im=ImageOps.exif_transpose(Image.open(ROOT/src['path'])).convert('RGB')
        assert list(im.size)==x['image_size'] and src['sha256']==sha((ROOT/src['path']).read_bytes())
        boxes=[yolo_box([b[0],b[1],b[2]-b[0],b[3]-b[1]],*im.size) for b in x['boxes_xyxy']]
        row={**src,'split':'train','boxes_yolo':boxes,'annotation_scope':'Visually reviewed binary waste boxes',
             'annotation_file':supplement.relative_to(ROOT).as_posix()}
        kept.append(row)
    data=ROOT/'data/cache/detection-v07'
    import shutil
    for split in priority:
        sub=[r for r in kept if r['split']==split]
        write(ROOT/f'data/manifests/detection_{split}_v07.json',sub)
        for r in sub:
            src=ROOT/r['path'];dst=data/'images'/split/(r['id']+'.jpg');dst.parent.mkdir(parents=True,exist_ok=True)
            # Re-encode supplements with EXIF applied; TACO images already normalized.
            if r['id'].startswith('commons-'):ImageOps.exif_transpose(Image.open(src)).convert('RGB').save(dst,quality=95,subsampling=0)
            else:shutil.copyfile(src,dst)
            lab=data/'labels'/split/(r['id']+'.txt');lab.parent.mkdir(parents=True,exist_ok=True)
            lab.write_text('\n'.join('0 '+' '.join(f'{v:.8f}' for v in b) for b in r['boxes_yolo'])+'\n',encoding='utf-8')
    (data/'data.yaml').write_text('path: '+data.as_posix()+'\ntrain: images/train\nval: images/validation\ntest: images/test\nnames:\n  0: waste object\n',encoding='utf-8')
    write(OUT/'data-audit.json',{'excluded':excluded,'counts':{s:sum(r['split']==s for r in kept) for s in priority},
        'objects':{s:sum(len(r['boxes_yolo']) for r in kept if r['split']==s) for s in priority},
        'warning':'Batch separation is not proven photographer independence. dHash is only a heuristic. No four-category labels inferred from TACO.'})
    print(read(OUT/'data-audit.json')['counts'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['download','finalize']);p.add_argument('--extend-supported-test',action='store_true');a=p.parse_args()
    if a.stage=='download':download(a.extend_supported_test)
    else:finalize()
