"""获取带逐图许可元数据的候选图片；仅做资源采集，分类真值须另行复核。"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
from io import BytesIO
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
QUERIES={
    "recyclable":'filetype:bitmap plastic bottles -diagram -logo',
    "kitchen":'filetype:bitmap food waste -diagram -logo -map',
    "other":'filetype:bitmap cigarette butts -diagram -logo',
    "hazardous":'filetype:bitmap compact fluorescent lamp -diagram -x-ray -logo',
}
HEADERS={"User-Agent":"GarbageVisionEducational/0.1 (local coursework; Wikimedia Commons attribution retained)"}

def fetch(url):
    """有界重试；服务不可用时保留失败记录，不生成替代图片。"""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=40) as response:
                return response.read()
        except Exception:
            if attempt==2:raise
            time.sleep(2*(attempt+1))

def clean(value):
    return html.unescape(re.sub('<[^>]+>','',value or ''))

def main():
    """保存原始元数据、下载校验和及去重信息，尚不运行任何识别模型。"""
    records=[]; failures=[]
    (ROOT/'data/manifests').mkdir(parents=True,exist_ok=True)
    for group,query in QUERIES.items():
        params=dict(action='query',generator='search',gsrsearch=query,gsrnamespace=6,gsrlimit=24,
                    prop='imageinfo',iiprop='url|extmetadata|sha1|size',iiurlwidth=960,format='json')
        data=json.loads(fetch('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(params)))
        pages=sorted(data.get('query',{}).get('pages',{}).values(),key=lambda p:p.get('index',0))
        for page in pages:
            info=page['imageinfo'][0]; meta=info.get('extmetadata',{})
            license_name=meta.get('LicenseShortName',{}).get('value','')
            if not (license_name.startswith('CC BY') or license_name in ['CC0','Public domain']):continue
            identifier='commons-'+str(page['pageid'])
            records.append(dict(id=identifier,source_group=group,title=page['title'],source_page=info['descriptionurl'],
                download_url=info.get('thumburl',info['url']).split('?')[0],original_url=info['url'],original_sha1=info['sha1'],
                license=license_name,license_url=meta.get('LicenseUrl',{}).get('value',''),
                author=clean(meta.get('Artist',{}).get('value','')),description=clean(meta.get('ImageDescription',{}).get('value','')),
                review_status='unreviewed',path=f'data/raw/commons/{identifier}.jpg'))
        print(group,len(pages),'candidates',flush=True)
    # 同一来源页不因出现在多个搜索结果中而计作多张独立图片。
    records=list({r['id']:r for r in records}.values())
    def download(record):
        try:
            target=ROOT/record['path']; target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():target.write_bytes(fetch(record['download_url']))
            raw=target.read_bytes(); im=Image.open(BytesIO(raw)).convert('RGB');im.load()
            small=list(im.resize((9,8)).convert('L').getdata())
            dh=sum((small[y*9+x]>small[y*9+x+1])<<(y*8+x) for y in range(8) for x in range(8))
            record.update(sha256=hashlib.sha256(raw).hexdigest(),dhash=f'{dh:016x}',width=im.width,height=im.height)
            return record
        except Exception as error:
            failures.append({'id':record['id'],'error':str(error)})
            return None
    with ThreadPoolExecutor(max_workers=3) as pool:
        valid=[r for r in pool.map(download,records) if r]
    # 在任何模型推理前分组；同作者同搜索组保守视作同来源组，避免连拍泄漏。
    parent=list(range(len(valid)))
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,a in enumerate(valid):
        for j,b in enumerate(valid[:i]):
            if (a['author'] and a['author']==b['author'] and a['source_group']==b['source_group']) or a['sha256']==b['sha256'] or (int(a['dhash'],16)^int(b['dhash'],16)).bit_count()<=5:
                parent[find(i)]=find(j)
    for i,r in enumerate(valid):
        group=valid[find(i)]['id'];r['group_id']=group
        rank=int(hashlib.sha256(('commons-v1:'+group).encode()).hexdigest()[:8],16)%100
        r['split']='dev' if rank<35 else 'test'
    (ROOT/'data/manifests/commons_candidates.json').write_text(json.dumps(valid,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'data/manifests/commons_download_errors.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf-8')
    print('downloaded',len(valid),'failed',len(failures),flush=True)

if __name__=='__main__':main()
