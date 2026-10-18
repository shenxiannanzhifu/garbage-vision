"""单张图片真实本地推理入口：python scripts/infer.py 图片路径 --output exports/单图。"""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.config import local_settings
from garbage_vision.images import decode_image
from garbage_vision.local import infer_local
from garbage_vision.exports import annotate,export_json,export_csv

def main():
    parser=argparse.ArgumentParser(description='本地垃圾识别：SAM + CLIP')
    parser.add_argument('image',type=Path);parser.add_argument('--output',type=Path,default=Path('exports/单图'))
    parser.add_argument('--device',choices=['auto','cpu','cuda:0'],default='auto')
    args=parser.parse_args();source=decode_image(args.image.read_bytes());settings=local_settings();settings['device']=args.device
    result=infer_local(source,settings);args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'result.json').write_bytes(export_json([result]));(args.output/'result.csv').write_bytes(export_csv([result]))
    (args.output/'annotated.png').write_bytes(annotate(source,result))
    print(f'成功：{len(result.items)} 个候选物品，{result.elapsed_seconds:.2f} 秒；结果位于 {args.output.resolve()}')

if __name__=='__main__':main()
