"""Reproduce public TACO archive index/annotations and pinned YOLOv8n weights."""
import hashlib,json,struct,sys,zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from garbage_vision.config import ROOT

OUT=ROOT/'data/cache/taco-source'
ARCHIVE='https://zenodo.org/api/records/3587843/files/TACO.zip/content'
MODEL='https://hf-mirror.com/Ultralytics/YOLOv8/resolve/27f858f2dc238503a66ce10248cf7ec71a3ded5d/yolov8n.pt'

def main():
    import httpx
    OUT.mkdir(parents=True,exist_ok=True)
    with httpx.Client(trust_env=False,timeout=90,follow_redirects=True) as client:
        def span(start,size):
            # Never consume the whole multi-GB archive if the server ignores Range.
            with client.stream('GET',ARCHIVE,headers={'Range':f'bytes={start}-{start+size-1}'}) as r:
                r.raise_for_status()
                if r.status_code!=206:raise ValueError('HTTP Range was not honored')
                data=b''.join(r.iter_bytes())
            if len(data)!=size:raise ValueError('Incomplete archive range')
            return data
        # Frozen official v1 archive length/central directory from EOCD. Confirm
        # before interpreting entries, avoiding silent use of another archive.
        tail=span(2719810615-65536,65536);end=struct.unpack_from('<4s4H2LH',tail,tail.rfind(b'PK\x05\x06'))
        if end[4:7]!=(1981,175830,2719634763):raise ValueError('Official archive layout changed')
        central=span(end[6],end[5]);pos=0;entries={}
        while central[pos:pos+4]==b'PK\x01\x02':
            v=struct.unpack_from('<4s6H3L5H2L',central,pos)
            name=central[pos+46:pos+46+v[10]].decode('utf-8')
            entries[name]={'method':v[4],'compressed':v[8],'size':v[9],'offset':v[16],'crc':v[7]}
            pos+=46+v[10]+v[11]+v[12]
        (OUT/'zip-index.json').write_text(json.dumps(entries,indent=2),encoding='utf-8')
        e=entries['TACO/data/annotations.json'];head=struct.unpack('<4s5H3L2H',span(e['offset'],30))
        data=span(e['offset']+30+head[-2]+head[-1],e['compressed'])
        if e['method']==8:data=zlib.decompress(data,-15)
        assert len(data)==e['size'] and zlib.crc32(data)==e['crc']
        if hashlib.sha256(data).hexdigest()!='ac1ec605c9e1fcda767970de3457c69b4a43b62c02aca8c4c80f51d1b5ae8449':raise ValueError('Annotation hash changed')
        (OUT/'archive-annotations.json').write_bytes(data)
        weights=OUT/'yolov8n.pt'
        expected='31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95'
        if not weights.exists():
            r=client.get(MODEL);r.raise_for_status()
            if hashlib.sha256(r.content).hexdigest()!=expected:raise ValueError('Model hash mismatch')
            weights.write_bytes(r.content)
        if hashlib.sha256(weights.read_bytes()).hexdigest()!=expected:raise ValueError('Local model hash mismatch')
    print('Verified archive metadata, annotations and pinned initial weights.')

if __name__=='__main__':main()
