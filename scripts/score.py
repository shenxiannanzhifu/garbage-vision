"""由完整清单和真实预测生成评分；不加载模型、不调用网络、不改变已有预测。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from garbage_vision.evaluation import score_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    evidence = json.loads(args.predictions.read_text(encoding='utf-8'))
    manifest_hash = hashlib.sha256(raw).hexdigest()
    # Git 可转换 CRLF/LF；只容忍换行编码不同，原始图像字节哈希仍必须完全一致。
    lf = raw.decode('utf-8').replace('\r\n','\n')
    equivalent_hashes = {manifest_hash, hashlib.sha256(lf.encode()).hexdigest(),
                         hashlib.sha256(lf.replace('\n','\r\n').encode()).hexdigest()}
    if evidence['manifest_sha256'] not in equivalent_hashes:
        raise SystemExit('预测的清单哈希与当前清单不符，拒绝评分。')
    report = score_records(manifest, evidence['records'])
    report.update(manifest_sha256=manifest_hash,
                  predictions_sha256=hashlib.sha256(args.predictions.read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('records', 'per_category')}, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
