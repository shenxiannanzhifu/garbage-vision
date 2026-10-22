"""One explicitly authorized remote HTTP task; never automatically resubmit a paid call."""
import argparse
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from garbage_vision.api import api_settings
from garbage_vision.images import decode_image
from garbage_vision.service_client import request
from scripts.nexavlinks_trial import estimate_nex, reservation_nex

SAMPLES = ('commons-179028310.jpg', 'commons-79273563.jpg')


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('sample', choices=SAMPLES)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--confirm-paid-api', action='store_true')
    p.add_argument('--budget-nex', type=float, default=0)
    p.add_argument('--resume', action='store_true', help='Only read an existing task; never resubmit it')
    args = p.parse_args()
    if not args.confirm_paid_api or not 0 < args.budget_nex <= 1:
        raise ValueError('Requires explicit authorization: these two samples, <=2 calls, <=1 NEX.')
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    marker = out/(args.sample+'.started.json')
    result_file = out/(args.sample+'.json')
    data = (ROOT/'data/raw/commons'/args.sample).read_bytes()
    source = decode_image(data)
    settings = api_settings()
    if settings.problem():
        raise ValueError(settings.problem())
    reserved = reservation_nex(source, settings)
    if args.resume:
        state = json.loads(marker.read_text(encoding='utf-8'))
        assert state['source_sha256'] == source.source_sha256
        task_id = state['task_id']
    else:
        if marker.exists() or result_file.exists():
            raise RuntimeError('Request already recorded. Use --resume only if task_id was saved; never auto-resubmit.')
        previous = list(out.glob('*.started.json'))
        if len(previous) >= 2:
            raise RuntimeError('Authorized two-call limit reached.')
        spent = 0
        for prior in previous:
            done = out/prior.name.replace('.started.json', '.json')
            record = json.loads(done.read_text(encoding='utf-8'))
            if not record['verified'] or record['conservative_cost_nex'] is None:
                raise RuntimeError('Prior failure or unknown cost must be reviewed before another paid request.')
            spent += record['conservative_cost_nex']
        if spent + reserved > args.budget_nex:
            raise RuntimeError('Insufficient remaining authorized budget.')
        key = str(uuid4())
        state = {'sample': args.sample, 'source_sha256': source.source_sha256,
                 'request_key': key, 'started_at': datetime.now(timezone.utc).isoformat(),
                 'max_calls': 2, 'budget_nex': args.budget_nex, 'reserved_nex': reserved}
        # Record before network submission; an interrupted response is unresolved, not retryable.
        save(marker, state)
        response = request('POST', '/v1/tasks', files={'file': (args.sample, data)},
                           data={'include_api': 'true'}, headers={'Idempotency-Key': key}).json()
        task_id = response['id']
        state['task_id'] = task_id
        save(marker, state)
        print(json.dumps({'task_id': task_id, 'sample': args.sample, 'reserved_nex': reserved}), flush=True)
    deadline = time.monotonic()+600
    while time.monotonic() < deadline:
        task = request('GET', '/v1/tasks/'+task_id).json()
        if task['status'] not in {'queued', 'running'}:
            break
        time.sleep(1)
    exported = request('GET', f'/v1/tasks/{task_id}/export').json()
    api = task.get('results', {}).get('api') or {}
    cost = estimate_nex(api.get('metadata', {}).get('usage', {}))
    record = {'sample': args.sample, 'task_id': task_id, 'verified': False,
              'conservative_cost_nex': cost, 'cost_note': 'Upper-group estimate; provider billing log is authoritative.',
              'export': exported}
    save(result_file, record)
    assert task['status'] == 'succeeded', task.get('error') or task['status']
    assert task['local_status'] == task['api_status'] == 'success'
    assert task['source_sha256'] == source.source_sha256
    server_png = request('GET', f'/v1/tasks/{task_id}/image').content
    assert hashlib.sha256(server_png).hexdigest() == task['image_id']
    with Image.open(BytesIO(server_png)) as im:
        assert im.convert('RGB').tobytes() == source.image.tobytes() and im.size == source.image.size
    for method in ('local', 'api'):
        result = task['results'][method]
        assert result['status'] == 'success'
        assert result['image_id'] == task['image_id'] and result['source_sha256'] == source.source_sha256
    assert task['results']['local']['metadata']['device'] == 'cuda:0'
    assert api['metadata']['sent_image_sha256'] == task['image_id']
    assert api['metadata']['provider'] == 'nexavlinks' and api['metadata']['attempts'] == 1
    assert exported['task']['results'] == task['results']
    assert cost is not None and cost <= reserved, 'Usage exceeded reserved estimate; stop and reconcile billing.'
    (out/(task_id+'-annotated.png')).write_bytes(request('GET', f'/v1/tasks/{task_id}/annotated').content)
    record.update(verified=True, same_image_verified=True, export_matches=True,
                  local_device='cuda:0', attempts=1)
    save(result_file, record)
    print(json.dumps({k: v for k, v in record.items() if k != 'export'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
