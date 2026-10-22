"""维护检查：只读取现有任务；停服备份后在副本验证恢复，不发送模型请求。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from garbage_vision.service_client import request


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def snapshot():
    tasks = []
    offset = 0
    while True:
        page = request('GET', '/v1/tasks', params={'limit': 100, 'offset': offset}).json()['tasks']
        for row in page:
            task_id = row['id']
            task = request('GET', '/v1/tasks/' + task_id).json()
            if task['status'] in {'queued', 'running'}:
                raise RuntimeError('还有任务未完成，请完成后再执行维护验证。')
            image = request('GET', f'/v1/tasks/{task_id}/image').content
            tasks.append({'task': task, 'image_sha256': hashlib.sha256(image).hexdigest()})
        offset += len(page)
        if len(page) < 100:
            break
    return sorted(tasks, key=lambda row: row['task']['id'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['snapshot', 'backup', 'compare'])
    parser.add_argument('run_dir', type=Path)
    args = parser.parse_args()
    folder = args.run_dir.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    before_path = folder/'before.json'
    if args.action == 'snapshot':
        if before_path.exists():
            raise RuntimeError('此次维护目录已使用，请新建目录以保留旧记录。')
        rows = snapshot()
        if not rows:
            raise RuntimeError('没有可用于持久化验证的历史任务。')
        write_json(before_path, rows)
        print(f'已保存{len(rows)}项任务的维护前快照；未重新识别。')
    elif args.action == 'backup':
        # 调用方必须先停止API；不备份正在写入的SQLite文件。
        before = json.loads(before_path.read_text(encoding='utf-8'))
        data = ROOT/'.local/container-data'
        shutil.copytree(data, folder/'backup')
        shutil.copytree(folder/'backup', folder/'restore-copy')
        hashes = {p.relative_to(data).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in data.rglob('*') if p.is_file()}
        for relative, expected in hashes.items():
            assert hashlib.sha256((folder/'backup'/relative).read_bytes()).hexdigest() == expected
        write_json(folder/'backup-manifest.json', hashes)
        write_json(folder/'restore-copy/expected-tasks.json', before)
        print('停服数据备份与逐文件哈希校验通过；恢复测试使用另一份副本。')
    else:
        before = json.loads(before_path.read_text(encoding='utf-8'))
        after = snapshot()
        if before != after:
            raise RuntimeError('重建后的任务/结果/图片与维护前快照不一致。')
        write_json(folder/'after.json', after)
        write_json(folder/'persistence.json', {'complete': True, 'task_count': len(after),
            'full_task_results_unchanged': True, 'image_hashes_unchanged': True,
            'inference_requests_sent': 0})
        print(f'容器重建后{len(after)}项历史、结果和图片一致；没有新建识别任务。')


if __name__ == '__main__':
    main()
