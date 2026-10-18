"""获取第二轮候选，仅记录来源及许可；人工/视觉复核并冻结后才能运行模型。"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
from io import BytesIO
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
from PIL import Image,ImageDraw,ImageOps

ROOT=Path(__file__).resolve().parents[2]
QUERIES={
 'recyclable':['glass bottles','aluminium beverage cans','cardboard boxes'],
 'kitchen':['banana peels','apple cores','vegetable food scraps'],
 'other':['cigarette butts ashtray','discarded cigarettes','used paper tissues'],
 'hazardous':['spiral fluorescent lamp','compact fluorescent light bulbs','fluorescent tubes'],
 'unknown':['LED light bulb','incandescent light bulbs','alkaline batteries'],
}

def fetch(url):
    proxy=urllib.request.ProxyHandler({'https':'http://127.0.0.1:7897'})
    opener=urllib.request.build_opener(proxy)
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'GarbageVisionEducational/0.5 (attribution retained)'}),timeout=45) as r:return r.read()

def clean(value):return html.unescape(re.sub('<[^>]+>','',value or ''))

def main():
    target=ROOT/'data/manifests/quality_candidates.json'
    if target.exists():raise SystemExit('Candidate manifest already exists; do not overwrite.')
    old=json.loads((ROOT/'data/manifests/commons_candidates.json').read_text(encoding='utf-8'))
    oldids={r['id'] for r in old};oldauthors={r['author'] for r in old if r['author']}
    oldsha={r['sha256'] for r in old};olddh=[int(r['dhash'],16) for r in old]
    found={};errors=[]
    for group,queries in QUERIES.items():
        for query in queries:
            params=dict(action='query',generator='search',gsrsearch='filetype:bitmap '+query+' -diagram -logo -drawing',gsrnamespace=6,gsrlimit=12,
                        prop='imageinfo',iiprop='url|extmetadata|sha1|size',iiurlwidth=960,format='json')
            try:pages=json.loads(fetch('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(params))).get('query',{}).get('pages',{})
            except Exception as e:errors.append({'query':query,'error':type(e).__name__});continue
            for page in sorted(pages.values(),key=lambda x:x.get('index',0)):
                i=page['imageinfo'][0];m=i.get('extmetadata',{});lic=m.get('LicenseShortName',{}).get('value','')
                author=clean(m.get('Artist',{}).get('value',''));identifier='commons-'+str(page['pageid'])
                if not (lic.startswith('CC BY') or lic in ['CC0','Public domain']):continue
                if identifier in oldids or author in oldauthors or identifier in found:continue
                found[identifier]=dict(id=identifier,source_group=group,query=query,title=page['title'],author=author,
                    source_page=i['descriptionurl'],download_url=i.get('thumburl',i['url']).split('?')[0],original_url=i['url'],
                    license=lic,license_url=m.get('LicenseUrl',{}).get('value',''),description=clean(m.get('ImageDescription',{}).get('value','')),
                    path=f'data/raw/quality-v2/{identifier}.jpg',review_status='unreviewed')
            print(group,query,len(found),flush=True)
    def download(r):
        try:
            p=ROOT/r['path'];p.parent.mkdir(parents=True,exist_ok=True)
            if not p.exists():p.write_bytes(fetch(r['download_url']))
            raw=p.read_bytes();im=Image.open(BytesIO(raw)).convert('RGB');im.load()
            pixels=list(im.resize((9,8)).convert('L').getdata())
            dh=sum((pixels[y*9+x]>pixels[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))
            sha=hashlib.sha256(raw).hexdigest()
            if sha in oldsha or any((dh-v).bit_count()<=5 for v in olddh):return None
            r.update(sha256=sha,dhash=f'{dh:016x}',width=im.width,height=im.height)
            return r
        except Exception as e:errors.append({'id':r['id'],'error':type(e).__name__});return None
    with ThreadPoolExecutor(max_workers=3) as pool:rows=[r for r in pool.map(download,found.values()) if r]
    target.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (target.parent/'quality_download_errors.json').write_text(json.dumps(errors,indent=2),encoding='utf-8')
    cache=ROOT/'data/cache/quality-review';cache.mkdir(parents=True,exist_ok=True)
    for group in QUERIES:
        items=[r for r in rows if r['source_group']==group]
        for page in range(0,len(items),20):
            batch=items[page:page+20];canvas=Image.new('RGB',(1200,240*((len(batch)+4)//5)),(235,235,235));d=ImageDraw.Draw(canvas)
            for n,r in enumerate(batch):
                x=(n%5)*240;y=(n//5)*240
                with Image.open(ROOT/r['path']) as im:thumb=ImageOps.contain(im.convert('RGB'),(230,205))
                canvas.paste(thumb,(x+(240-thumb.width)//2,y));d.text((x+5,y+208),r['id'],fill='black')
            canvas.save(cache/f'{group}-{page//20}.jpg')
    print('downloaded',len(rows),'errors',len(errors),flush=True)

if __name__=='__main__':main()
