"""固定 CLIP 源码版本，直接构建 wheel，避免本机隔离构建临时目录 ACL 问题。"""
import hashlib
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REV='7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40'
SHA='ea6799c740f2725175edee0881de9f354086e801dd33d4f43b17d18c8238fb54'

def main():
    local=ROOT/'.local';local.mkdir(exist_ok=True)
    archive=local/'clip-source.zip'
    if not archive.exists():
        with urllib.request.urlopen(f'https://codeload.github.com/ultralytics/CLIP/zip/{REV}',timeout=90) as response:archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA:raise RuntimeError('CLIP 源码归档校验失败')
    source_root=local/'clip-source';source_root.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            target=(source_root/entry.filename).resolve()
            if not target.is_relative_to(source_root.resolve()):raise ValueError('归档路径超出源码目录')
        z.extractall(source_root)
    wheel_dir=local/'clip-wheel';wheel_dir.mkdir(exist_ok=True)
    source=source_root/f'CLIP-{REV}'
    subprocess.run([sys.executable,'-c','from setuptools import setup; setup()','bdist_wheel','--dist-dir',str(wheel_dir)],cwd=source,check=True)
    wheel=wheel_dir/'clip-1.0-py3-none-any.whl'
    # 依赖由 requirements.txt 统一安装，避免构建后的重复联网及意外升级。
    subprocess.run([str(ROOT/'.tools/uv.exe'),'pip','install','--no-deps','--python',sys.executable,str(wheel)],check=True)
    subprocess.run([sys.executable,'-c','import clip,ftfy,regex,torch; assert callable(clip.load)'],check=True)
    (local/'clip-source-revision.txt').write_text(REV,encoding='utf-8')
    print('CLIP 固定源码构建与安装完成：',REV)

if __name__=='__main__':main()
