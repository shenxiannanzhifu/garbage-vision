"""人工核对中断账单后继续未发送的图；不改冻结源码、不重发失败图。"""
import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_nexavlinks import DIRECTORY, verify
from scripts.nexavlinks_trial import estimate_nex, reservation_nex
from garbage_vision.api import api_settings, infer_api
from garbage_vision.config import ROOT, weight_hash
from garbage_vision.experiment import write_new_json
from garbage_vision.images import decode_image


def accounted_cost(out, reviews):
    """所有已启动请求均须有结果；失败须单独审核且文件未变化。"""
    starts = list(out.glob('*.started.json'))
    spent = 0.0
    for marker in starts:
        target = marker.with_name(marker.name.replace('.started.json', '.json'))
        if not target.exists():
            raise ValueError('Unresolved started request; stop.')
        record = json.loads(target.read_text(encoding='utf-8'))
        if record['result']['status'] == 'success' and record['estimated_cost_nex'] is not None:
            spent += record['estimated_cost_nex']
            continue
        review = reviews.get(record['id'])
        if not review or review['result_sha256'] != weight_hash(target) or review['marker_sha256'] != weight_hash(marker):
            raise ValueError('Unreviewed failure or changed evidence; stop.')
        if review['action'] != 'skip_without_retry':
            raise ValueError('Review must forbid retry.')
        cost = review['actual_cost_nex']
        if cost is None and not review.get('unknown_cost_reserved_authorized', False):
            raise ValueError('Unknown billing requires explicit user authorization to reserve and skip.')
        # 保留原请求的完整预算预留，比已核对的站内扣款更保守。
        reserved = json.loads(marker.read_text(encoding='utf-8'))['reserved_nex']
        if cost is not None and not 0 <= cost <= reserved:
            raise ValueError('Reviewed cost exceeds original reservation.')
        spent += reserved
    return len(starts), spent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-reviewed-resume', action='store_true')
    parser.add_argument('--review-file', default='interruption-review.json')
    parser.add_argument('--direct', action='store_true')
    args = parser.parse_args()
    if not args.confirm_reviewed_resume:
        raise ValueError('Manual diagnosis and reviewed resume required.')
    frozen = json.loads((DIRECTORY/'freeze.json').read_text(encoding='utf-8'))
    review_file = DIRECTORY/args.review_file
    reviews = json.loads(review_file.read_text(encoding='utf-8'))['reviewed_failures']
    settings = replace(api_settings(), enabled=True, max_attempts=1)
    if args.direct:
        settings = replace(settings, proxy_url='')
    if settings.problem():
        raise ValueError(settings.problem())
    verify(frozen, settings)
    out = DIRECTORY/'api'
    accounted_cost(out, reviews)
    # 只读预检：不发送图片、不进行模型生成、不跟随重定向。
    with httpx.Client(proxy=settings.proxy_url or None, timeout=20, trust_env=False, follow_redirects=False) as client:
        response = client.get(settings.base_url+'/models', headers={'Authorization': 'Bearer '+settings.key})
        if response.status_code != 200 or settings.model not in {x['id'] for x in response.json()['data']}:
            raise ValueError('Read-only model preflight failed; no generation sent.')
    for row in frozen['images']:
        target = out/(row['id']+'.json')
        marker = out/(row['id']+'.started.json')
        if target.exists():
            continue
        count, spent = accounted_cost(out, reviews)
        if count >= 40:
            raise ValueError('40-call authorization exhausted.')
        if weight_hash(ROOT/row['path']) != row['sha256']:
            raise ValueError('Image changed.')
        source = decode_image((ROOT/row['path']).read_bytes())
        reserve = reservation_nex(source, settings)
        if spent+reserve > 4:
            raise ValueError('Insufficient conservative budget; stop.')
        write_new_json(marker, {'id': row['id'], 'started_at_utc': datetime.now(timezone.utc).isoformat(),
            'authorized_budget_nex': 4, 'authorized_max_calls': 40, 'reserved_nex': reserve, 'attempts': 1,
            'reviewed_resume_sha256': weight_hash(review_file),
            'reviewed_resume_file':review_file.name, 'transport_route':'direct' if args.direct else 'configured_proxy'})
        result = infer_api(source, settings)
        cost = estimate_nex(result.metadata.get('usage', {}))
        write_new_json(target, {'id': row['id'], 'expected_categories': row['categories'],
            'result': result.model_dump(), 'estimated_cost_nex': cost,
            'pricing_note': 'Conservative higher-group estimate, not actual billed amount.'})
        print(row['id'], result.status, sorted(result.categories), 'conservative_nex', cost, flush=True)
        if result.status != 'success' or cost is None:
            raise ValueError('New failure/unknown usage; stop, no automatic retry or resume.')
    print('All 40 records preserved, including reviewed communication failure.', flush=True)


if __name__ == '__main__':
    main()
