"""服务边界测试使用明确的测试替身，不访问付费接口或宣称模型识别通过。"""
from io import BytesIO
import json
import os
import sqlite3
from pathlib import Path
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy.orm import Session

from garbage_vision.images import decode_image
from garbage_vision.schema import InferenceResult
from garbage_vision.service import Budget, ServiceSettings, Task, TaskService, create_app


@pytest.fixture
def tmp_path():
    # 使用继承目录权限的独立测试目录，避免Windows沙箱的0700临时目录限制。
    root=Path(os.getenv('CODEX_TEST_TMP',str(Path(__file__).resolve().parents[1]/'.local/test-temp')))
    target=root/('stage3-'+uuid4().hex)
    target.mkdir(parents=True)
    return target


def picture(color='white'):
    buf=BytesIO();Image.new('RGB',(32,24),color).save(buf,format='PNG');return buf.getvalue()


def fake_local(source, settings):
    return InferenceResult(image_id=source.image_id,source_sha256=source.source_sha256,
        image_size=source.image.size,method='local',model='TEST DOUBLE - not real inference',
        status='success',metadata={'test_double':True})


def submit(client,data=None,key=None,**options):
    return client.post('/v1/tasks',files={'file':('../../escape.png',data or picture(),'image/png')},
        data=options,headers={'Idempotency-Key':key or str(uuid4())})


def finished(client,task_id):
    for _ in range(200):
        task=client.get('/v1/tasks/'+task_id).json()
        if task['status'] not in {'queued','running'}:return task
        time.sleep(.01)
    pytest.fail('test task did not finish')


def test_persistent_history_export_delete_and_idempotency(tmp_path):
    count=[]
    def local(source,settings):count.append(1);return fake_local(source,settings)
    settings=ServiceSettings(tmp_path/'service')
    key=str(uuid4())
    with TestClient(create_app(settings,local_runner=local)) as c:
        r=submit(c,key=key);assert r.status_code==202
        task_id=r.json()['id'];assert finished(c,task_id)['status']=='succeeded'
        assert submit(c,key=key).json()['id']==task_id
        assert submit(c,picture('red'),key=key).status_code==409
        assert c.get('/v1/tasks').json()['tasks'][0]['id']==task_id
        exported=c.get(f'/v1/tasks/{task_id}/export').json()['task']
        assert exported['results']['local']['image_id']==decode_image(picture()).image_id
        assert c.get(f'/v1/tasks/{task_id}/image').content==decode_image(picture()).png
        assert c.get(f'/v1/tasks/{task_id}/export?format=csv').status_code==200
    with TestClient(create_app(settings,local_runner=local)) as c:
        assert c.get('/v1/tasks/'+task_id).json()['status']=='succeeded'
        assert c.delete('/v1/tasks/'+task_id).status_code==200
        assert c.get('/v1/tasks/'+task_id).status_code==404
        assert submit(c,key=key).status_code==409
        assert not (settings.data_dir/'tasks'/task_id).exists()
    assert len(count)==1
    assert not (tmp_path/'escape.png').exists()


def test_bad_image_and_unapproved_fee_never_execute(tmp_path):
    calls=[]
    def no_call(*args):calls.append(1);raise AssertionError('must not execute')
    with TestClient(create_app(ServiceSettings(tmp_path),local_runner=no_call,api_runner=no_call)) as c:
        assert submit(c,data=b'not an image').status_code==422
        assert submit(c,include_api='true').status_code==403
        assert submit(c,key='wrong').status_code==422
        assert submit(c,similarity_min='0.9').status_code==422
        assert c.get('/v1/tasks?limit=9999').status_code==422
    assert not calls


def test_auth_and_partial_result_budget_survives_delete(tmp_path,monkeypatch):
    from garbage_vision.api import APISettings
    monkeypatch.setattr('garbage_vision.service.api_settings',lambda:APISettings(
        provider='nexavlinks',key='TEST-ONLY-FAKE',base_url='https://www.nexavlinks.com/v1',enabled=True))
    calls=[]
    def failed_api(source,settings):
        calls.append(1);assert settings.max_attempts==1
        raise RuntimeError('TEST-ONLY-SECRET must not appear in output')
    settings=ServiceSettings(tmp_path,token='test-token',paid_limit=1,authorization_id='TEST-ONLY-GRANT')
    with TestClient(create_app(settings,local_runner=fake_local,api_runner=failed_api)) as c:
        assert c.get('/v1/tasks').status_code==401
        c.headers['Authorization']='Bearer test-token'
        response=submit(c,include_api='true');assert response.status_code==202
        task_id=response.json()['id'];task=finished(c,task_id)
        assert task['status']=='partial' and task['local_status']=='success' and task['api_status']=='error'
        assert 'TEST-ONLY-SECRET' not in json.dumps(task)
        assert c.delete('/v1/tasks/'+task_id).status_code==200
        assert submit(c,include_api='true').status_code==403
        assert c.get('/health/ready').json()['paid_calls_remaining']==0
    assert len(calls)==1


def test_restart_marks_interrupted_no_automatic_resume(tmp_path):
    settings=ServiceSettings(tmp_path)
    with TestClient(create_app(settings,local_runner=fake_local)) as c:
        r=submit(c);task_id=r.json()['id'];finished(c,task_id)
        with Session(c.app.state.service.engine) as db:
            task=db.get(Task,task_id);task.status='running';task.api_status='running';db.commit()
    calls=[]
    def no_call(*args):calls.append(1);raise AssertionError('must not resume')
    with TestClient(create_app(settings,local_runner=no_call,api_runner=no_call)) as c:
        task=c.get('/v1/tasks/'+task_id).json()
        assert task['status']=='interrupted' and task['api_status']=='unknown'
        assert task['local_status']=='success'
    assert not calls


def test_busy_delete_and_queue_bound(tmp_path):
    gate=threading.Event()
    def local(source,settings):gate.wait(5);return fake_local(source,settings)
    try:
        with TestClient(create_app(ServiceSettings(tmp_path,max_pending=1),local_runner=local)) as c:
            task_id=submit(c).json()['id']
            assert c.delete('/v1/tasks/'+task_id).status_code==409
            assert submit(c).status_code==429
            gate.set();assert finished(c,task_id)['status']=='succeeded'
    finally:gate.set()


def test_schema_adopts_legacy_database_without_changing_history(tmp_path):
    settings = ServiceSettings(tmp_path)
    with TestClient(create_app(settings, local_runner=fake_local)) as client:
        task_id = submit(client).json()['id']
        before = finished(client, task_id)
    with sqlite3.connect(tmp_path/'tasks.sqlite3') as db:
        db.execute('PRAGMA user_version = 0')
    with TestClient(create_app(settings, local_runner=fake_local)) as client:
        assert client.get('/v1/tasks/'+task_id).json() == before
    with sqlite3.connect(tmp_path/'tasks.sqlite3') as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1


@pytest.mark.parametrize('incompatible', ['version', 'columns'])
def test_incompatible_database_rejected_without_changes_or_lock_leak(tmp_path, incompatible):
    path = tmp_path/'tasks.sqlite3'
    with sqlite3.connect(path) as db:
        if incompatible == 'version':
            db.execute('PRAGMA user_version = 99')
        else:
            db.execute('CREATE TABLE tasks (id TEXT PRIMARY KEY)')
    before = path.read_bytes()
    for _ in range(2):
        with pytest.raises(RuntimeError, match='不兼容'):
            TaskService(ServiceSettings(tmp_path))
        assert path.read_bytes() == before


def test_missing_prompt_does_not_create_task_or_reserve_budget(tmp_path, monkeypatch):
    from garbage_vision.api import APISettings
    monkeypatch.setattr('garbage_vision.service.api_settings', lambda: APISettings(
        provider='nexavlinks', key='TEST-ONLY-FAKE', base_url='https://www.nexavlinks.com/v1', enabled=True))
    monkeypatch.setattr('garbage_vision.service.PROMPT_PATH', tmp_path/'missing-prompt.txt')
    calls = []
    def forbidden(*args):
        calls.append(True)
        raise AssertionError('must not execute')
    settings = ServiceSettings(tmp_path/'data', token='test-token', paid_limit=1, authorization_id='TEST-ONLY-GRANT')
    with TestClient(create_app(settings, local_runner=forbidden, api_runner=forbidden)) as client:
        client.headers['Authorization'] = 'Bearer test-token'
        assert submit(client, include_api='true').status_code == 409
        assert client.get('/v1/tasks').json()['tasks'] == []
        assert client.get('/health/ready').json()['paid_calls_remaining'] == 1
        with Session(client.app.state.service.engine) as db:
            assert db.get(Budget, settings.authorization_id) is None
    assert not calls


def test_manual_calls_require_opt_in_and_keep_idempotency_and_history(tmp_path, monkeypatch):
    from garbage_vision.api import APISettings
    monkeypatch.setattr('garbage_vision.service.api_settings', lambda: APISettings(
        provider='nexavlinks', key='TEST-ONLY-FAKE', base_url='https://www.nexavlinks.com/v1', enabled=True))
    calls = []
    def api(source, settings):
        calls.append(source.image_id)
        return fake_local(source, settings).model_copy(update={'method': 'api'})
    cfg = ServiceSettings(tmp_path, token='test-token', authorization_id='TEST-MANUAL', paid_manual=True)
    with TestClient(create_app(cfg, local_runner=fake_local, api_runner=api)) as c:
        assert c.get('/v1/tasks').status_code == 401
        c.headers['Authorization'] = 'Bearer test-token'
        ready = c.get('/health/ready').json()
        assert ready['paid_calls_enabled'] and ready['paid_calls_remaining'] is None
        local_id = submit(c).json()['id']
        assert finished(c, local_id)['api_status'] == 'skipped' and not calls
        # More than the former two-call allowance works, only with explicit opt-in.
        for _ in range(3):
            key = str(uuid4())
            r = submit(c, key=key, include_api='true'); assert r.status_code == 202
            task_id = r.json()['id']; assert finished(c, task_id)['status'] == 'succeeded'
            duplicate = submit(c, key=key, include_api='true').json()
            assert duplicate['id'] == task_id and duplicate['created'] is False
        with Session(c.app.state.service.engine) as db:
            grant = db.get(Budget, cfg.authorization_id)
            assert grant.call_limit == -1 and grant.reserved == 3
    with TestClient(create_app(cfg, local_runner=fake_local, api_runner=api)) as c:
        c.headers['Authorization'] = 'Bearer test-token'
        assert len(c.get('/v1/tasks').json()['tasks']) == 4
        assert c.get('/v1/tasks/'+task_id).json()['status'] == 'succeeded'
    assert len(calls) == 3  # Restart/history/duplicate submission did not call again.


def test_manual_mode_cannot_rewrite_a_finite_authorization(tmp_path, monkeypatch):
    from garbage_vision.api import APISettings
    monkeypatch.setattr('garbage_vision.service.api_settings', lambda: APISettings(
        provider='nexavlinks', key='TEST-ONLY-FAKE', base_url='https://www.nexavlinks.com/v1', enabled=True))
    cfg = ServiceSettings(tmp_path, token='test-token', authorization_id='TEST-FINITE', paid_manual=True)
    calls = []
    def forbidden(*args):
        calls.append(True)
        raise AssertionError('must not call')
    with TestClient(create_app(cfg, local_runner=forbidden, api_runner=forbidden)) as c:
        with Session(c.app.state.service.engine) as db:
            db.add(Budget(id=cfg.authorization_id, call_limit=2, reserved=2)); db.commit()
        c.headers['Authorization'] = 'Bearer test-token'
        assert submit(c, include_api='true').status_code == 409
        with Session(c.app.state.service.engine) as db:
            grant = db.get(Budget, cfg.authorization_id)
            assert grant.call_limit == grant.reserved == 2
    assert not calls
