"""下载已核实的本地模型权重并校验 SHA256；不接受校验失败的文件。"""
import hashlib
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
WEIGHTS={
    'sam2.1_t.pt':('https://github.com/ultralytics/assets/releases/download/v8.3.0/sam2.1_t.pt','3c1e81ca9b037dd39d70a014ddb9a813d6c4c4e12555420db7eaff31689bd4e3'),
    'ViT-B-32.pt':('https://openaipublic.azureedge.net/clip/models/40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt','40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af')}

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as file:
        for part in iter(lambda:file.read(4*1024*1024),b''):h.update(part)
    return h.hexdigest()

def main():
    (ROOT/'weights').mkdir(exist_ok=True)
    for name,(url,sha) in WEIGHTS.items():
        target=ROOT/'weights'/name
        if target.exists() and digest(target)==sha:
            print('已校验：',name);continue
        partial=target.with_suffix('.download')
        print('正在下载：',name,flush=True)
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'GarbageVision/0.2'}),timeout=120) as response,partial.open('wb') as file:
            for block in iter(lambda:response.read(4*1024*1024),b''):file.write(block)
        if digest(partial)!=sha:raise RuntimeError(f'{name} 校验失败，保留 .download 文件便于排查，不加载。')
        partial.replace(target);print('下载并校验完成：',name)

if __name__=='__main__':main()
