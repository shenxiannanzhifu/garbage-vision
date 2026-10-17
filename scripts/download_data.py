"""按冻结清单获取开发/测试图片；校验原字节，失败不替换成其他图片。"""
import argparse,hashlib,json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=['dev','test','all'],default='dev');args=parser.parse_args()
    splits=['dev','test'] if args.split=='all' else [args.split]
    for split in splits:
        for row in json.loads((ROOT/f'data/manifests/{split}.json').read_text(encoding='utf-8')):
            path=(ROOT/row['path']).resolve()
            if not path.is_relative_to((ROOT/'data/raw').resolve()):raise ValueError('清单路径超出原始数据目录')
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']:continue
            request=urllib.request.Request(row['download_url'],headers={'User-Agent':'GarbageVisionEducational/0.2 (Wikimedia Commons attribution retained)'})
            with urllib.request.urlopen(request,timeout=60) as response:raw=response.read()
            if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError(f"来源内容已变化：{row['id']}；不得静默改测试集")
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);print('下载并校验',row['id'],flush=True)
    print('数据校验完成；许可与署名见清单中的 source_page、author、license。')

if __name__=='__main__':main()
