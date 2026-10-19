"""下载第三轮公开许可候选；标签和划分必须视觉复核后另行冻结，不调用模型。"""
import argparse,hashlib,html,json,re,sys,urllib.parse,urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[2]
QUERIES={
 'plastic bottle':['empty plastic bottles','PET bottle recycling'],
 'glass bottle':['empty beer bottles','glass bottles recycling'],
 'metal can':['crushed aluminium can','empty beverage cans'],
 'cardboard box':['flattened cardboard boxes','cardboard waste'],
 'banana peel':['banana peel waste'],
 'apple core':['apple core food'],
 'food waste':['food scraps compost','vegetable peelings'],
 'cigarette butt':['cigarette butts','cigarette litter'],
 'used tissue':['used tissue paper'],
 'compact fluorescent lamp':['compact fluorescent lamp bulb'],
 'fluorescent tube':['fluorescent tube lamp'],
 'battery':['battery cells'],
 'LED light bulb':['LED light bulb'],
 'incandescent light bulb':['incandescent light bulb'],
 'background':['empty ashtray','empty recycling bins','stone pavement','empty desk'],
}

def fetch(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'}))
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'GarbageVisionEducational/0.6 (CC attribution retained)'}),timeout=25) as r:return r.read()

def clean(value):return html.unescape(re.sub('<[^>]+>','',value or ''))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--supplement',action='store_true');args=parser.parse_args()
    suffix='supplement' if args.supplement else 'candidates'
    queries={k:QUERIES[k] for k in ['cigarette butt','used tissue','compact fluorescent lamp','fluorescent tube','battery','LED light bulb','incandescent light bulb']} if args.supplement else QUERIES
    target=ROOT/f'data/manifests/training_{suffix}_v06.json'
    if target.exists():raise SystemExit('Preserve existing candidate manifest.')
    old=[]
    for name in ['commons_candidates.json','quality_candidates.json','quality_supplement.json']:
        old.extend(json.loads((ROOT/'data/manifests'/name).read_text(encoding='utf-8')))
    if args.supplement:old.extend(json.loads((target.parent/'training_candidates_v06.json').read_text(encoding='utf-8')))
    oldids={r['id'] for r in old}
    oldtest=[]
    for name in ['test.json','quality_test.json']:
        oldtest.extend(json.loads((ROOT/'data/manifests'/name).read_text(encoding='utf-8')))
    excluded_authors={r['author'].strip() for r in oldtest}
    errors=[]
    def search(entry):
        label,query=entry
        params=dict(action='query',generator='search',gsrsearch='filetype:bitmap '+query+' -diagram -logo -drawing',gsrnamespace=6,gsrlimit=35,
                    prop='imageinfo',iiprop='url|extmetadata|sha1|size',iiurlwidth=960,format='json')
        try:
            pages=json.loads(fetch('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(params))).get('query',{}).get('pages',{})
            rows=[]
            for page in sorted(pages.values(),key=lambda x:x.get('index',0)):
                i=page['imageinfo'][0];m=i.get('extmetadata',{});lic=m.get('LicenseShortName',{}).get('value','')
                author=clean(m.get('Artist',{}).get('value',''));key='commons-'+str(page['pageid'])
                if key in oldids or author.strip() in excluded_authors:continue
                if not (lic.startswith('CC BY') or lic in ['CC0','Public domain']):continue
                rows.append(dict(id=key,query_label=label,query=query,title=page['title'],author=author,
                    source_page=i['descriptionurl'],download_url=i.get('thumburl',i['url']).split('?')[0],
                    license=lic,license_url=m.get('LicenseUrl',{}).get('value',''),description=clean(m.get('ImageDescription',{}).get('value','')),
                    path=f'data/raw/training-v06/{key}.jpg',review_status='unreviewed'))
            print('search',label,len(rows),flush=True);return rows
        except Exception as e:errors.append({'query':query,'error':type(e).__name__});return []
    found={}
    with ThreadPoolExecutor(max_workers=1 if args.supplement else 3) as pool:
        for rows in pool.map(search,[(label,q) for label,qs in queries.items() for q in qs]):
            for row in rows:found.setdefault(row['id'],row)
    # Deterministic per-label caps before downloads or predictions.
    selected=[]
    for label in queries:
        selected.extend([r for r in found.values() if r['query_label']==label][:16 if args.supplement else 24 if label!='background' else 32])
    oldsha={r['sha256'] for r in old};olddh=[int(r['dhash'],16) for r in old]
    def download(r):
        try:
            path=ROOT/r['path'];path.parent.mkdir(parents=True,exist_ok=True)
            raw=path.read_bytes() if path.exists() else fetch(r['download_url'])
            im=Image.open(BytesIO(raw))
            if im.format not in ['JPEG','PNG','WEBP']:raise ValueError('Unsupported photograph format')
            im=ImageOps.exif_transpose(im).convert('RGB');im.load()
            if min(im.size)<80:raise ValueError('Image too small')
            pixels=list(im.resize((9,8)).convert('L').getdata())
            dh=sum((pixels[y*9+x]>pixels[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))
            sha=hashlib.sha256(raw).hexdigest()
            if sha in oldsha or any((dh^v).bit_count()<=5 for v in olddh):return None
            if not path.exists():path.write_bytes(raw)
            r.update(sha256=sha,dhash=f'{dh:016x}',width=im.width,height=im.height)
            return r
        except Exception as e:errors.append({'id':r['id'],'error':type(e).__name__});return None
    with ThreadPoolExecutor(max_workers=4) as pool:rows=[r for r in pool.map(download,selected) if r]
    target.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (target.parent/f'training_{suffix}_errors_v06.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
    out=ROOT/f'data/cache/training-review-v06/{suffix}';out.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14)
    for start in range(0,len(rows),16):
        canvas=Image.new('RGB',(1280,1120),'white');d=ImageDraw.Draw(canvas)
        for j,r in enumerate(rows[start:start+16]):
            x=j%4*320;y=j//4*280
            with Image.open(ROOT/r['path']) as im:t=ImageOps.contain(ImageOps.exif_transpose(im).convert('RGB'),(314,240))
            canvas.paste(t,(x+(320-t.width)//2,y+30))
            d.text((x+3,y+2),r['id'],font=font,fill='black');d.text((x+3,y+16),r['query_label'],font=font,fill='black')
        canvas.save(out/f'sheet-{start//16+1:02}.jpg',quality=93)
    print('DONE',len(rows),'candidate images;',len(errors),'errors. No inference performed.',flush=True)

if __name__=='__main__':main()
