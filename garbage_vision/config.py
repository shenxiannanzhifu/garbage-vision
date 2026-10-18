"""集中读取项目配置。所有默认路径相对仓库，避免依赖终端所在目录。"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read_json(path: str):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))

def rules():
    """物品词表、分类规则及说明；更改配置后重新运行即可生效。"""
    return read_json('config/categories.json')

def local_settings():
    return read_json('config/local_model.json')

def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

@lru_cache(maxsize=8)
def file_sha256(path: str, size: int, modified: int) -> str:
    """按文件状态缓存大权重校验值；重启进程或文件改变后重新计算。"""
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(4*1024*1024),b''): h.update(part)
    return h.hexdigest()

def weight_hash(path: Path) -> str:
    s=path.stat()
    return file_sha256(str(path),s.st_size,s.st_mtime_ns)
