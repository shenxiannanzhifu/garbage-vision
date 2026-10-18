"""离线测量开发图无损上传候选体积；不请求API，不估称实际网络提速。"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.config import ROOT
from garbage_vision.images import decode_image
from garbage_vision.image_transport import prepare_lossless_upload


def main():
    rows=json.loads((ROOT/'data/manifests/dev.json').read_text(encoding='utf-8'))
    records=[]
    for row in rows:
        original=(ROOT/row['path']).read_bytes()
        source=decode_image(original)
        started=time.perf_counter()
        candidate,mime,mode=prepare_lossless_upload(original,source)
        records.append({'id':row['id'],'canonical_png_bytes':len(source.png),'candidate_bytes':len(candidate),
                        'mime':mime,'mode':mode,'preparation_seconds':time.perf_counter()-started})
    before=sum(r['canonical_png_bytes'] for r in records);after=sum(r['candidate_bytes'] for r in records)
    report={'scope':'19 development images, offline only; no API requests','before_bytes':before,
        'after_bytes':after,'upload_bytes_reduction':1-after/before,'records':records,
        'accuracy_or_latency_improvement_claimed':False,'enabled_in_real_evaluation':False}
    out=ROOT/'evidence/v0.5.0/transport-optimization';out.mkdir(exist_ok=True)
    (out/'offline-benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'}))


if __name__=='__main__':main()
