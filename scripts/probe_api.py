"""单张开发样例的真实 API 联调；必须显式确认收费，关闭自动重试并保存原始结果。"""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from garbage_vision.api import api_settings, infer_api
from garbage_vision.config import ROOT
from garbage_vision.images import decode_image


def main():
    """仅使用冻结开发清单；拒绝覆盖证据，绝不把测试集用于接口调试。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--id', default='commons-179028310')
    parser.add_argument('--confirm-single-paid-call', action='store_true')
    args = parser.parse_args()
    if not args.confirm_single_paid_call:
        parser.error('先取得单次付费调用授权，再显式添加 --confirm-single-paid-call')
    settings = replace(api_settings(), max_attempts=1, max_tokens=2048)
    if (settings.provider!='dashscope' or settings.model!='qwen3-vl-plus'
            or settings.base_url!='https://dashscope.aliyuncs.com/compatible-mode/v1'):
        raise SystemExit('此旧脚本仅适用于百炼；OpenAI 请使用 scripts/openai_trial.py 及其美元预算。')
    if settings.problem():
        raise SystemExit(settings.problem())
    manifest_path = ROOT / 'data/manifests/dev.json'
    rows = json.loads(manifest_path.read_text(encoding='utf-8'))
    row = next((r for r in rows if r['id'] == args.id), None)
    if row is None:
        raise SystemExit('只能选择已冻结的开发图片。')
    raw = (ROOT / row['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise SystemExit('原始图片与冻结清单不符。')
    source = decode_image(raw)
    # 调用前创建唯一证据目录，避免网络已计费但无法写结果；保留中断痕迹。
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT / 'evidence/v0.3.0' / ('api-probe-' + stamp)
    out.mkdir(parents=True, exist_ok=False)
    record = {'id': row['id'], 'image_id': source.image_id,
              'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              'max_attempts': 1, 'max_output_tokens': 2048,
              'budget_authorization_yuan': 0.10, 'status': 'started'}
    target = out / 'result.json'
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    result = infer_api(source, settings)
    usage = result.metadata.get('usage', {})
    prompt = usage.get('prompt_tokens')
    completion = usage.get('completion_tokens')
    # 北京 qwen3-vl-plus 非思考模式公开价格；估算不是账单，免费额度不作假定。
    estimate = None
    if isinstance(prompt, int) and isinstance(completion, int):
        factor = 1 if prompt <= 32000 else 1.5 if prompt <= 128000 else 3
        estimate = round((prompt + completion * 10) * factor / 1_000_000, 8)
    record.update(status='finished', result=result.model_dump(), estimated_cost_yuan=estimate,
                  billing_note='按公开价格和返回 usage 估算；以服务商账单为准。')
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': result.status, 'categories': sorted(result.categories),
                      'error': result.error, 'usage': usage, 'estimated_cost_yuan': estimate,
                      'elapsed_seconds': result.elapsed_seconds, 'evidence': str(target)}, ensure_ascii=False))
    return 0 if result.status == 'success' else 1


if __name__ == '__main__':
    raise SystemExit(main())
