"""通过stdin在隔离Linux容器验证备份副本，绝不使用原服务数据目录。"""
import hashlib
import json
from pathlib import Path
import platform
from sqlalchemy import select
from sqlalchemy.orm import Session
from garbage_vision.service import ServiceSettings, TaskService, Task

data = Path('/data')
expected = json.loads((data/'expected-tasks.json').read_text(encoding='utf-8'))
calls = []


def forbidden_inference(*args):
    calls.append(True)
    raise RuntimeError('恢复检查不得调用模型')


assert platform.system() == 'Linux'
service = TaskService(ServiceSettings(data), local_runner=forbidden_inference, api_runner=forbidden_inference)
try:
    with Session(service.engine) as db:
        ids = sorted(db.scalars(select(Task.id).where(Task.deleted == False)))
    assert ids == sorted(row['task']['id'] for row in expected)
    for row in expected:
        task_id = row['task']['id']
        assert service.get(task_id) == row['task']
        assert hashlib.sha256((service.folder(task_id)/'image.png').read_bytes()).hexdigest() == row['image_sha256']
finally:
    service.close()
assert not calls
result = {'complete': True, 'platform': platform.platform(), 'restored_tasks': len(expected),
          'task_results_and_images_match': True, 'inference_calls': len(calls), 'original_data_modified': False}
(data/'restore-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
