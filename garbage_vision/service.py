"""三阶段单实例服务：任务状态落库，执行上下文在单进程中；重启不重发收费请求。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import shutil
from threading import RLock
import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from filelock import FileLock, Timeout
from sqlalchemy import Boolean, Integer, String, Text, create_engine, inspect, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .api import PROMPT_PATH, api_settings, infer_api
from .config import ROOT, fingerprint, local_settings
from .exports import annotate, export_csv
from .images import MAX_BYTES, decode_image
from .local import _engine, infer_local
from .schema import InferenceResult

LOG = logging.getLogger('garbage_vision.service')
ACTIVE = {'queued', 'running'}
SCHEMA_VERSION = 1


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(36), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    image_id: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24))
    local_status: Mapped[str] = mapped_column(String(24))
    api_status: Mapped[str] = mapped_column(String(24))
    options_json: Mapped[str] = mapped_column(Text)
    config_sha256: Mapped[str] = mapped_column(String(64))
    local_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Budget(Base):
    __tablename__ = 'api_authorizations'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    call_limit: Mapped[int] = mapped_column(Integer)
    reserved: Mapped[int] = mapped_column(Integer, default=0)


@dataclass(frozen=True)
class ServiceSettings:
    data_dir: Path
    token: str = ''
    device: str = 'auto'
    paid_limit: int = 0
    authorization_id: str = ''
    max_pending: int = 8

    @classmethod
    def from_env(cls):
        return cls(Path(os.getenv('GV_S3_DATA_DIR', str(ROOT/'.local/stage3-data'))),
                   os.getenv('GV_S3_ACCESS_TOKEN', ''), os.getenv('GV_S3_DEVICE', 'auto'),
                   int(os.getenv('GV_S3_PAID_CALL_LIMIT', '0')),
                   os.getenv('GV_S3_AUTHORIZATION_ID', ''), int(os.getenv('GV_S3_MAX_PENDING', '8')))


class TaskService:
    def __init__(self, settings, local_runner=infer_local, api_runner=infer_api):
        self.settings = settings
        if settings.device not in {'auto', 'cpu', 'cuda:0'}:
            raise ValueError('GV_S3_DEVICE只能是auto、cpu或cuda:0')
        if settings.paid_limit < 0 or not 1 <= settings.max_pending <= 32:
            raise ValueError('任务上限或收费次数配置无效')
        self.data = settings.data_dir.resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.files = self.data/'tasks'
        self.files.mkdir(exist_ok=True)
        self.process_lock = FileLock(str(self.data/'service.lock'))
        try:
            self.process_lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError('同一数据目录只允许运行一个API实例；请使用--workers 1。') from exc
        self.lock = RLock()
        self.engine = create_engine('sqlite:///'+(self.data/'tasks.sqlite3').as_posix(),
                                    connect_args={'check_same_thread': False, 'timeout': 30})
        # 兼容本阶段最早的未标版本数据库，只接纳相同结构；未来迁移需显式备份和升级。
        try:
            with self.engine.begin() as conn:
                version = conn.exec_driver_sql('PRAGMA user_version').scalar()
                if version not in (0, SCHEMA_VERSION):
                    raise RuntimeError('数据库结构版本不兼容，请先备份并按迁移说明升级。')
                existing = inspect(conn)
                for table in Base.metadata.sorted_tables:
                    if existing.has_table(table.name):
                        actual = {c['name'] for c in existing.get_columns(table.name)}
                        if actual != {c.name for c in table.columns}:
                            raise RuntimeError('数据库表结构不兼容；未修改原数据，请先备份。')
                Base.metadata.create_all(conn)
                conn.exec_driver_sql('PRAGMA user_version = 1')
        except Exception:
            self.engine.dispose()
            self.process_lock.release()
            raise
        self.local_runner, self.api_runner = local_runner, api_runner
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gv-inference')
        self.recover()

    def recover(self):
        with self.lock, Session(self.engine) as db, db.begin():
            for task in db.scalars(select(Task).where(Task.status.in_(ACTIVE))):
                was_calling = task.api_status == 'running'
                task.status = 'interrupted'
                task.updated_at = now()
                task.error = '服务重启中断了任务；已保存结果保留，不会自动重新识别或发送收费请求。'
                if task.local_status in ACTIVE:
                    task.local_status = 'interrupted'
                if task.api_status in ACTIVE:
                    task.api_status = 'unknown' if was_calling else 'interrupted'

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.recover()
        self.engine.dispose()
        self.process_lock.release()

    def folder(self, task_id):
        # 仅使用系统生成的UUID；用户上传的文件名不参与路径计算。
        try:
            canonical = str(UUID(task_id))
        except ValueError:
            raise HTTPException(404, '任务不存在')
        return self.files/canonical

    def task(self, db, task_id):
        task = db.get(Task, task_id)
        if task is None or task.deleted:
            raise HTTPException(404, '任务不存在')
        return task

    def view(self, task, full=True):
        result = {key: getattr(task, key) for key in (
            'id', 'image_id', 'source_sha256', 'created_at', 'updated_at', 'status',
            'local_status', 'api_status', 'config_sha256', 'error')}
        result['options'] = json.loads(task.options_json)
        if full:
            result['results'] = {method: json.loads(value) for method, value in (
                ('local', task.local_json), ('api', task.api_json)) if value}
        return result

    def get(self, task_id):
        with self.lock, Session(self.engine) as db:
            return self.view(self.task(db, task_id))

    def capabilities(self):
        with self.lock, Session(self.engine) as db:
            grant = db.get(Budget, self.settings.authorization_id) if self.settings.authorization_id else None
            remaining = max(0, self.settings.paid_limit - (grant.reserved if grant else 0))
        return {'paid_calls_enabled': bool(self.settings.token and self.settings.authorization_id and remaining),
                'paid_calls_remaining': remaining if self.settings.authorization_id else 0,
                'execution': 'single_process_background', 'max_pending': self.settings.max_pending}

    def submit(self, data, request_key, include_api=False, similarity=.28):
        try:
            request_key = str(UUID(request_key))
        except ValueError:
            raise HTTPException(422, 'Idempotency-Key必须是UUID；重复提交同一任务请复用原值。')
        if not .20 <= similarity <= .40:
            raise HTTPException(422, '相似度下限必须在0.20至0.40之间')
        try:
            source = decode_image(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        options = {'include_api': include_api, 'similarity_min': similarity}
        request_hash = fingerprint({'source': source.source_sha256, **options})
        with self.lock, Session(self.engine) as db:
            old = db.scalar(select(Task).where(Task.request_key == request_key))
            if old:
                if old.request_hash != request_hash:
                    raise HTTPException(409, '该提交编号已用于不同图片或选项')
                if old.deleted:
                    raise HTTPException(409, '该任务已删除，原提交编号保留防重记录；请明确创建新任务。')
                return self.view(old), False
            pending = len(list(db.scalars(select(Task.id).where(Task.status.in_(ACTIVE)))))
            if pending >= self.settings.max_pending:
                raise HTTPException(429, '等待任务已满，请稍后重试')
            configured = None
            if include_api:
                cfg = self.settings
                if not cfg.token or not cfg.authorization_id or cfg.paid_limit <= 0:
                    raise HTTPException(403, '本阶段尚未配置新的收费调用授权；当前仅可运行本地模型。')
                configured = api_settings()
                if configured.problem():
                    raise HTTPException(409, '多模态接口本地配置不完整；请在本机配置文件中核对。')
                grant = db.get(Budget, cfg.authorization_id)
                if grant is None:
                    grant = Budget(id=cfg.authorization_id, call_limit=cfg.paid_limit, reserved=0)
                    db.add(grant)
                if grant.call_limit != cfg.paid_limit:
                    raise HTTPException(409, '已有授权次数不可在原授权编号下改写')
                if grant.reserved >= grant.call_limit:
                    raise HTTPException(403, '本次授权次数已用完或已预留；不会自动追加或重试。')
                grant.reserved += 1
            settings = local_settings()
            settings.update(device=self.settings.device, similarity_min=similarity)
            # 在任务和收费次数预留落库前读取提示词；缺失时不会留下永远排队的任务。
            try:
                prompt_hash = hashlib.sha256((ROOT/PROMPT_PATH).read_bytes()).hexdigest() if include_api else None
            except OSError:
                raise HTTPException(409, '多模态提示词不可读取；未创建任务或预留收费次数。')
            public_config = {'local': settings}
            if configured:
                public_config['api'] = {name: getattr(configured, name) for name in (
                    'provider', 'base_url', 'model', 'timeout', 'max_tokens', 'reasoning_effort',
                    'image_detail', 'image_transport')}
                public_config['api']['prompt_sha256'] = prompt_hash
                public_config['api']['max_attempts'] = 1
            task_id = str(uuid4())
            folder = self.folder(task_id)
            folder.mkdir()
            try:
                (folder/'input.bin').write_bytes(data)
                (folder/'image.png').write_bytes(source.png)
                task = Task(id=task_id, request_key=request_key, request_hash=request_hash,
                            image_id=source.image_id, source_sha256=source.source_sha256,
                            created_at=now(), updated_at=now(), status='queued', local_status='queued',
                            api_status='queued' if include_api else 'skipped',
                            options_json=json.dumps(options), config_sha256=fingerprint(public_config))
                db.add(task)
                db.commit()
            except Exception:
                db.rollback()
                shutil.rmtree(folder)
                raise
            result = self.view(task)
            self.executor.submit(self.execute, task_id, settings, configured, prompt_hash)
            LOG.info('task=%s state=queued', task_id)
            return result, True

    def update(self, task_id, **values):
        with self.lock, Session(self.engine) as db, db.begin():
            task = db.get(Task, task_id)
            for name, value in values.items():
                setattr(task, name, value)
            task.updated_at = now()

    def execute(self, task_id, settings, configured=None, prompt_hash=None):
        try:
            self.update(task_id, status='running', local_status='running')
            source = decode_image((self.folder(task_id)/'input.bin').read_bytes())
            snapshot = self.get(task_id)
            for method in ['local'] + (['api'] if snapshot['options']['include_api'] else []):
                self.update(task_id, **{method+'_status': 'running'})
                start = time.perf_counter()
                try:
                    if method == 'local':
                        result = self.local_runner(source, settings)
                    else:
                        # 独立读取同图，不传本地预测；强制一次尝试，网络失败也不重试。
                        if hashlib.sha256((ROOT/PROMPT_PATH).read_bytes()).hexdigest() != prompt_hash:
                            raise ValueError('任务等待期间提示词发生变更，已停止发送请求')
                        result = self.api_runner(source, replace(configured, max_attempts=1))
                    if result.image_id != source.image_id or result.source_sha256 != source.source_sha256:
                        raise ValueError('模型结果图片标识不匹配')
                except Exception as exc:
                    # 不把任意异常正文写入日志，避免网络库或提供商错误中夹带凭据。
                    result = InferenceResult(image_id=source.image_id, source_sha256=source.source_sha256,
                        image_size=source.image.size, method=method, model='SAM2.1-tiny + CLIP' if method=='local' else 'configured multimodal API',
                        status='error', error='本地模型执行失败，请检查权重、依赖及设备。' if method=='local' else '远端请求失败，未自动重试，请核对记录及账单。',
                        elapsed_seconds=time.perf_counter()-start, metadata={'error_type': type(exc).__name__})
                self.update(task_id, **{method+'_status': result.status, method+'_json': result.model_dump_json()})
                LOG.info('task=%s method=%s state=%s', task_id, method, result.status)
            completed = self.get(task_id)
            states = [completed['local_status']] + ([completed['api_status']] if completed['options']['include_api'] else [])
            status = 'succeeded' if all(x=='success' for x in states) else 'partial' if 'success' in states else 'failed'
            self.update(task_id, status=status)
        except Exception as exc:
            LOG.error('task=%s failure_type=%s', task_id, type(exc).__name__)
            current = self.get(task_id)
            updates = {'status': 'interrupted', 'error': '任务执行中断，已保存结果保留；不会自动重发。'}
            if current['local_status'] in ACTIVE:
                updates['local_status'] = 'interrupted'
            if current['api_status'] in ACTIVE:
                updates['api_status'] = 'unknown' if current['api_status']=='running' else 'interrupted'
            self.update(task_id, **updates)


def create_app(settings=None, local_runner=infer_local, api_runner=infer_api):
    settings = settings or ServiceSettings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        app.state.service = TaskService(settings, local_runner, api_runner)
        try:
            yield
        finally:
            app.state.service.close()

    app = FastAPI(title='识废 · 三阶段 API', version='3.0.0-dev', lifespan=lifespan)

    def access(authorization: Annotated[str | None, Header()] = None):
        if settings.token and not secrets.compare_digest((authorization or '').encode('utf-8'), ('Bearer '+settings.token).encode('utf-8')):
            raise HTTPException(401, '需要有效访问凭据', headers={'WWW-Authenticate': 'Bearer'})

    def service():
        return app.state.service

    protected = [Depends(access)]

    @app.get('/health/live')
    def live():
        return {'status': 'alive'}

    @app.get('/health/ready', dependencies=protected)
    def ready():
        cfg = local_settings()
        missing = [Path(cfg[k]).name for k in ['sam_weights', 'clip_weights'] if not (ROOT/cfg[k]).is_file()]
        return {'ready_for_tasks': not missing, 'missing_weights': missing,
                'model_loaded': bool(_engine.cache_info().currsize),
                'note': '权重文件存在不等于真实模型推理通过；请查看实际任务记录。',
                **service().capabilities()}

    @app.post('/v1/tasks', status_code=202, dependencies=protected)
    async def submit(file: UploadFile = File(...), include_api: bool = Form(False),
                     similarity_min: float = Form(.28),
                     idempotency_key: Annotated[str, Header(alias='Idempotency-Key')] = ''):
        data = await file.read(MAX_BYTES+1)
        await file.close()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, '上传超过12MB')
        result, created = service().submit(data, idempotency_key, include_api, similarity_min)
        return {**result, 'created': created}

    @app.get('/v1/tasks', dependencies=protected)
    def history(limit: int = 20, offset: int = 0):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(422, '分页参数无效')
        svc = service()
        with svc.lock, Session(svc.engine) as db:
            tasks = db.scalars(select(Task).where(Task.deleted == False).order_by(Task.created_at.desc()).offset(offset).limit(limit))
            return {'tasks': [svc.view(t, full=False) for t in tasks], 'limit': limit, 'offset': offset}

    @app.get('/v1/tasks/{task_id}', dependencies=protected)
    def detail(task_id: str):
        return service().get(task_id)

    @app.get('/v1/tasks/{task_id}/image', dependencies=protected)
    def image(task_id: str):
        svc = service()
        with svc.lock:
            svc.get(task_id)
            return Response((svc.folder(task_id)/'image.png').read_bytes(), media_type='image/png')

    @app.get('/v1/tasks/{task_id}/annotated', dependencies=protected)
    def annotated(task_id: str):
        svc = service()
        with svc.lock:
            task = svc.get(task_id)
            result = task['results'].get('local')
            if not result or result['status'] != 'success':
                raise HTTPException(409, '本地结果尚不可用')
            source = decode_image((svc.folder(task_id)/'input.bin').read_bytes())
            return Response(annotate(source, InferenceResult.model_validate(result)), media_type='image/png')

    @app.get('/v1/tasks/{task_id}/export', dependencies=protected)
    def export(task_id: str, format: str = 'json'):
        task = service().get(task_id)
        if format == 'json':
            content = json.dumps({'schema_version': 'stage3-task-v1', 'task': task}, ensure_ascii=False, indent=2).encode('utf-8')
            media = 'application/json'
        elif format == 'csv':
            content = export_csv([InferenceResult.model_validate(x) for x in task['results'].values()])
            media = 'text/csv'
        else:
            raise HTTPException(422, '仅支持json或csv')
        return Response(content, media_type=media,
                        headers={'Content-Disposition': f'attachment; filename="{task["id"]}.{format}"'})

    @app.delete('/v1/tasks/{task_id}', dependencies=protected)
    def delete(task_id: str):
        svc = service()
        with svc.lock, Session(svc.engine) as db:
            task = svc.task(db, task_id)
            if task.status in ACTIVE:
                raise HTTPException(409, '运行中的任务不可删除')
            folder = svc.folder(task_id)
            # 自生成UUID目录才可删，不跟随目录符号链接。
            if folder.is_symlink():
                raise HTTPException(409, '任务数据目录异常，请人工检查')
            if folder.exists():
                shutil.rmtree(folder)
            task.deleted = True
            task.local_json = task.api_json = None
            db.commit()
            return {'deleted': True, 'id': task_id,
                    'note': '保留最小提交防重记录和已预留收费次数，不重复识别或退还不确定次数。'}

    return app
