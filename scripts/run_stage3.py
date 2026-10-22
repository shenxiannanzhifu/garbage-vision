"""本机入口：只改当前进程的缓存/配置，密钥不打印。"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def prepare():
    from dotenv import dotenv_values
    config=ROOT/'.env.stage3'
    if not config.exists():
        config.write_text('GV_S3_ACCESS_TOKEN='+secrets.token_urlsafe(32)+'\n'
            'GV_S3_API_URL=http://127.0.0.1:8000\nGV_S3_DEVICE=auto\n'
            'GV_S3_PAID_CALL_LIMIT=0\nGV_S3_AUTHORIZATION_ID=\n',encoding='utf-8')
    for key,value in dotenv_values(config).items():
        if value is not None:os.environ.setdefault(key,value)
    for key,sub in [('UV_CACHE_DIR','uv-cache'),('MPLCONFIGDIR','matplotlib'),
        ('YOLO_CONFIG_DIR','ultralytics'),('TORCH_HOME','torch-cache'),
        ('HF_HOME','huggingface'),('TMP','temp'),('TEMP','temp')]:
        folder=ROOT/'.local'/sub;folder.mkdir(parents=True,exist_ok=True)
        os.environ[key]=str(folder)
    os.chdir(ROOT)


def main():
    parser=argparse.ArgumentParser(description='三阶段本机服务入口，默认仅监听本机')
    parser.add_argument('role',choices=['api','web'])
    args=parser.parse_args()
    prepare()
    if args.role=='api':
        import uvicorn
        from garbage_vision.service import create_app
        uvicorn.run(create_app(),host='127.0.0.1',port=8000,log_level='info')
    else:
        subprocess.run([sys.executable,'-m','streamlit','run','stage3_app.py',
            '--server.address','127.0.0.1','--server.port','8503',
            '--browser.gatherUsageStats','false'],check=True)


if __name__=='__main__':main()
