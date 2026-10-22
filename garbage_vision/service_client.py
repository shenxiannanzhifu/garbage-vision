"""页面只通过HTTP访问后端；重试仅适用于读取，创建任务不自动重发。"""
import os
import httpx
from dotenv import dotenv_values
from .config import ROOT


def connection():
    values={**dotenv_values(ROOT/'.env.stage3'),**os.environ}
    base=str(values.get('GV_S3_API_URL') or 'http://127.0.0.1:8000').rstrip('/')
    token=str(values.get('GV_S3_ACCESS_TOKEN') or '')
    return base, {'Authorization':'Bearer '+token} if token else {}


def request(method,path,**kwargs):
    base,headers=connection()
    with httpx.Client(base_url=base,headers=headers,timeout=30,trust_env=False) as client:
        response=client.request(method,path,**kwargs)
    if response.is_error:
        try:message=response.json().get('detail','接口请求失败')
        except ValueError:message='接口请求失败'
        raise RuntimeError(f'HTTP {response.status_code}：{message}')
    return response
