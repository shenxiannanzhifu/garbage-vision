"""冻结实验输入与运行条件，收费请求写入开始标记，防止中断后无意重复扣费。"""
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
from .api import api_settings, PROMPT_PATH
from .config import ROOT, local_settings, weight_hash
from .images import decode_image


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_hash(path):
    """源码按 UTF-8/LF 校验，避免 Git 的 Windows CRLF 转换导致同一提交无法复现。"""
    return hashlib.sha256(Path(path).read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def public_api_config(settings=None):
    """显式白名单，避免把密钥、密钥摘要或完整环境变量写入证据。"""
    s = settings or api_settings()
    return {k: getattr(s, k) for k in ('base_url', 'model', 'provider', 'timeout', 'max_tokens', 'use_env_proxy', 'reasoning_effort', 'image_detail', 'image_transport')}


def estimate_cost(usage):
    """北京 qwen3-vl-plus 非思考模式公开价估算；没有用量时返回未知。"""
    prompt, completion = usage.get('prompt_tokens'), usage.get('completion_tokens')
    if not isinstance(prompt, int) or not isinstance(completion, int) or min(prompt, completion) < 0:
        return None
    factor = 1 if prompt <= 32000 else 1.5 if prompt <= 128000 else 3
    return (prompt + 10 * completion) * factor / 1_000_000


def freeze_experiment(destination, split, ids=None):
    """正式测试必须完整冻结，开发联调可选择已声明的子集。此函数不运行模型。"""
    destination = Path(destination)
    if destination.exists():
        raise ValueError('实验目录已经存在，请使用新的目录，禁止覆盖证据。')
    if split == 'test' and ids:
        raise ValueError('正式测试不能挑选子集。')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise ValueError('先提交当前修改，再冻结可追溯实验。')
    manifest_path = ROOT / f'data/manifests/{split}.json'
    rows = json.loads(manifest_path.read_text(encoding='utf-8'))
    if ids:
        if not set(ids) <= {r['id'] for r in rows}:
            raise ValueError('开发图片 ID 不在清单中。')
        rows = [r for r in rows if r['id'] in ids]
    sources = []
    for row in rows:
        path = ROOT / row['path']
        if file_hash(path) != row['sha256']:
            raise ValueError('原始数据发生改变：' + row['id'])
        image = decode_image(path.read_bytes())
        sources.append({**row, 'image_id': image.image_id, 'image_size': list(image.image.size)})
    code = list((ROOT / 'garbage_vision').glob('*.py')) + list((ROOT / 'config').glob('*.json'))
    code += [ROOT / p for p in ['app.py', PROMPT_PATH, 'scripts/evaluate.py',
                                'scripts/score.py', 'scripts/generate_report.py', 'requirements.txt', 'requirements-build.txt']]
    settings = local_settings()
    frozen = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'split': split,
              'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'manifest_sha256': file_hash(manifest_path), 'manifest_text_sha256': text_hash(manifest_path),
              'manifest_path': str(manifest_path.relative_to(ROOT)), 'text_hash_format': 'utf8-lf-v1',
              'selected_ids': [r['id'] for r in sources], 'images': sources,
              'files': {p.relative_to(ROOT).as_posix(): text_hash(p) for p in code},
              'weights': {settings[k]: weight_hash(ROOT / settings[k]) for k in ('sam_weights', 'clip_weights')},
              'local_config': settings, 'api_config': public_api_config(), 'api_max_attempts': 1,
              'dependencies': {n: version(n) for n in ('torch', 'torchvision', 'ultralytics', 'clip',
                                'numpy', 'Pillow', 'httpx', 'pydantic', 'python-dotenv', 'streamlit', 'matplotlib')},
              'score_unit': 'per-image category presence set',
              'reference_labels': 'Commons author metadata + Codex pre-inference visual review; not independent human annotations'}
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'freeze.json').write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding='utf-8')
    return frozen


def verify_freeze(frozen, method):
    """不接受同一实验偷偷换模型、提示词、评分实现或运行依赖。"""
    source_hash = text_hash if frozen.get('text_hash_format') == 'utf8-lf-v1' else file_hash
    for rel, expected in frozen['files'].items():
        if source_hash(ROOT / rel) != expected:
            raise ValueError('冻结后文件被修改：' + rel)
    current_manifest = ROOT / frozen['manifest_path']
    if (text_hash(current_manifest) != frozen['manifest_text_sha256'] if 'manifest_text_sha256' in frozen
            else file_hash(current_manifest) != frozen['manifest_sha256']):
        raise ValueError('数据清单已改变。')
    for package, expected in frozen['dependencies'].items():
        if version(package) != expected:
            raise ValueError('运行依赖与冻结配置不同：' + package)
    if method == 'local':
        for rel, expected in frozen['weights'].items():
            if weight_hash(ROOT / rel) != expected:
                raise ValueError('权重与冻结配置不同。')
    elif public_api_config() != frozen['api_config']:
        raise ValueError('API 配置已改变，请创建新实验。')


def write_new_json(path, value):
    """独占创建，已有开始标记或结果不能覆盖。"""
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
