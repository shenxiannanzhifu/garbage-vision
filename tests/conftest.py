"""测试环境兼容：仅在显式指定时，临时目录继承工作区权限。"""
import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.environ.get("CODEX_TEST_TMP"):
    root = Path(os.environ["CODEX_TEST_TMP"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    def inherited_mkdtemp(suffix=None, prefix=None, dir=None):
        """绕过此 Windows 沙箱中不可访问的 0700 临时目录，不改全局权限。"""
        target = Path(dir or root) / f"{prefix or 'tmp'}{uuid.uuid4().hex}{suffix or ''}"
        target.mkdir()
        return str(target)
    tempfile.mkdtemp = inherited_mkdtemp
