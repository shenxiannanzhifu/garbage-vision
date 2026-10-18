"""冻结、批量运行、生成共同评分。API 运行需显式预算及授权参数；默认不重试。"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings, infer_api
from garbage_vision.config import ROOT
from garbage_vision.evaluation import score_records
from garbage_vision.experiment import (freeze_experiment, verify_freeze, file_hash,
                                      write_new_json, estimate_cost)
from garbage_vision.images import decode_image
from garbage_vision.schema import InferenceResult


def run_batch(directory, method, budget, max_calls, confirmed):
    """逐图落盘；API 中断后只允许读取已完成记录，不自动重发状态未知的请求。"""
    frozen = json.loads((directory / 'freeze.json').read_text(encoding='utf-8'))
    verify_freeze(frozen, method)
    settings = replace(api_settings(), max_attempts=1)
    if method == 'api':
        if not confirmed or budget <= 0 or max_calls < len(frozen['images']):
            raise ValueError('API 需要明确预算、覆盖图片数的请求上限及收费授权参数。')
        if settings.problem(): raise ValueError(settings.problem())
        if settings.provider != 'dashscope' or settings.model != 'qwen3-vl-plus':
            raise ValueError('当前预算估算只核实了北京 qwen3-vl-plus，其他模型需先核实定价。')
        if settings.base_url != 'https://dashscope.aliyuncs.com/compatible-mode/v1':
            raise ValueError('预算估算限定已核实的北京端点。')
    out = directory / method
    out.mkdir(exist_ok=True)
    records, charged_estimate = [], 0.0
    for row in frozen['images']:
        target, marker = out / (row['id'] + '.json'), out / (row['id'] + '.started.json')
        if target.exists():
            record = json.loads(target.read_text(encoding='utf-8'))
            records.append(record)
            charged_estimate += record.get('budget_accounted_yuan', 0)
            continue
        if marker.exists():
            raise ValueError('存在中断的请求标记，先核实服务商记录，禁止自动重试：' + row['id'])
        raw = (ROOT / row['path']).read_bytes()
        if file_hash(ROOT / row['path']) != row['sha256']:
            raise ValueError('图片与冻结数据不符：' + row['id'])
        source = decode_image(raw)
        if source.image_id != row['image_id']:
            raise ValueError('标准化图片哈希不同。')
        # 按 8K 输入+2048 输出约 0.02848 元估算，预留 0.05 元/图。
        # 这不是服务商硬限额；未知用量的失败按预留额占用预算并停止后续调用。
        if method == 'api' and charged_estimate + .05 > budget:
            raise ValueError('剩余预算不足以预留下一次请求，停止；已有结果保留。')
        if method == 'api' and len(list(out.glob('*.started.json'))) >= max_calls:
            raise ValueError('已达到请求次数上限。')
        write_new_json(marker, {'id': row['id'], 'method': method,
                               'started_at_utc': datetime.now(timezone.utc).isoformat(),
                               'image_id': source.image_id, 'max_attempts': 1,
                               'authorized_budget_yuan': budget if method == 'api' else None})
        try:
            if method == 'local':
                from garbage_vision.local import infer_local
                result = infer_local(source, frozen['local_config'])
            else:
                result = infer_api(source, settings)
        except (RuntimeError, OSError, ValueError, ImportError) as exc:
            result = InferenceResult(image_id=source.image_id, source_sha256=source.source_sha256,
                image_size=source.image.size, method=method, model=settings.model if method == 'api' else 'SAM2.1 + CLIP',
                status='error', error='执行失败，已记录异常类型。', metadata={'error_type': type(exc).__name__})
        cost = estimate_cost(result.metadata.get('usage', {})) if method == 'api' else 0
        accounted = cost if cost is not None else .05
        record = {'id': row['id'], 'expected_categories': row['categories'], 'result': result.model_dump(),
                  'estimated_cost_yuan': cost, 'budget_accounted_yuan': accounted}
        write_new_json(target, record)
        records.append(record)
        charged_estimate += accounted
        print(row['id'], result.status, sorted(result.categories), round(result.elapsed_seconds, 2), flush=True)
        if method == 'api' and cost is None:
            raise ValueError('本次没有可核实用量，暂停后续调用；失败记录保留，不自动重试。')
    aggregate = {'manifest_sha256': frozen['manifest_sha256'], 'freeze_sha256': file_hash(directory / 'freeze.json'),
                 'selected_ids': frozen['selected_ids'], 'records': records,
                 'estimated_cost_yuan': sum(r['estimated_cost_yuan'] or 0 for r in records),
                 'unknown_cost_records': sum(r['estimated_cost_yuan'] is None for r in records)}
    (out / 'predictions.json').write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding='utf-8')
    report = score_records(frozen['images'], records)
    (out / 'scores.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('images', 'mean_per_image_f1', 'exact_set_accuracy', 'failure_rate')}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    freeze = sub.add_parser('freeze'); freeze.add_argument('--output', type=Path, required=True)
    freeze.add_argument('--split', choices=['dev', 'test'], required=True)
    freeze.add_argument('--ids', nargs='+')
    run = sub.add_parser('run'); run.add_argument('directory', type=Path)
    run.add_argument('--method', choices=['local', 'api'], required=True)
    run.add_argument('--budget-yuan', type=float, default=0)
    run.add_argument('--max-api-calls', type=int, default=0)
    run.add_argument('--confirm-paid-api', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'freeze':
            frozen = freeze_experiment(args.output, args.split, args.ids)
            print('已冻结', len(frozen['images']), '张图片；没有运行模型或请求 API。')
        else:
            run_batch(args.directory, args.method, args.budget_yuan, args.max_api_calls, args.confirm_paid_api)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))


if __name__ == '__main__': main()
