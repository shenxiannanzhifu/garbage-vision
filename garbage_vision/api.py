"""可配置的图像理解 API 适配器。图片独立发送，绝不包含本地模型预测。"""
from dataclasses import dataclass, field
import base64
import hashlib
import json
import os
import re
import time
from urllib.parse import urlparse
import httpx
from dotenv import dotenv_values
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from .config import ROOT,rules,fingerprint
from .schema import Category,InferenceResult,Item

@dataclass
class APISettings:
    """密钥不参与 repr、页面配置展示或导出；只用于 Authorization 请求头。"""
    key: str=field(default='',repr=False)
    base_url: str=''
    model: str='qwen3-vl-plus'
    provider: str='dashscope'
    timeout: float=60
    max_tokens: int=2048
    max_attempts: int=2
    enabled: bool=False
    use_env_proxy: bool=False

    def problem(self):
        if not self.enabled:return '尚未启用图像理解 API；在本地 .env 中配置后启用。'
        if not self.key or not self.base_url:return '尚未填写 API 密钥或接口地址。'
        parsed=urlparse(self.base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return 'API 地址必须为不含凭据、查询参数的 HTTPS Base URL。'
        if not self.model:return '尚未配置模型名称。'
        return None

def api_settings():
    """每次读取本地配置，用户保存后无需重启；真实环境变量优先于 .env。"""
    values={**dotenv_values(ROOT/'.env'),**os.environ}
    workspace=str(values.get('GV_API_WORKSPACE_ID') or '').strip()
    base=str(values.get('GV_API_BASE_URL') or '').strip().rstrip('/')
    if not base and workspace:
        if not re.fullmatch(r'[A-Za-z0-9-]+',workspace):raise ValueError('业务空间 ID 只能包含字母、数字和连字符。')
        base=f'https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
    return APISettings(key=str(values.get('GV_API_KEY') or '').strip(),base_url=base,
        provider=str(values.get('GV_API_PROVIDER') or 'dashscope'),model=str(values.get('GV_API_MODEL') or 'qwen3-vl-plus'),
        timeout=max(5,min(180,float(values.get('GV_API_TIMEOUT') or 60))),
        max_tokens=max(256,min(4096,int(values.get('GV_API_MAX_TOKENS') or 2048))),
        max_attempts=max(1,min(2,int(values.get('GV_API_MAX_ATTEMPTS') or 2))),
        enabled=str(values.get('GV_API_ENABLED') or '').lower()=='true',
        use_env_proxy=str(values.get('GV_API_USE_ENV_PROXY') or '').lower()=='true')

class APIItem(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name: str=Field(min_length=1,max_length=100)
    category: Category | None
    reason: str=Field(min_length=1,max_length=1000)
    uncertain: bool

class APIResponse(BaseModel):
    model_config=ConfigDict(extra='forbid')
    items: list[APIItem]=Field(max_length=30)

def parse_response(text):
    """只容忍完整 JSON 外面的代码围栏；不猜测截断或错误的类别字段。"""
    if not isinstance(text,str) or len(text)>50000:raise ValueError('模型返回内容为空或过长。')
    cleaned=text.strip()
    if cleaned.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',cleaned,re.S)
        if not match:raise ValueError('模型返回的 JSON 围栏不完整。')
        cleaned=match.group(1)
    payload=APIResponse.model_validate_json(cleaned)
    return [Item(**x.model_dump()) for x in payload.items]

def infer_api(source,settings=None,transport=None,sleeper=time.sleep):
    """有界请求；429/502/503/504 最多重试一次，超时不重复付费提交。

    transport 只用于显式的单元测试替身。生产默认使用真实 HTTPS。
    """
    settings=settings or api_settings();started=time.perf_counter()
    base=dict(image_id=source.image_id,source_sha256=source.source_sha256,image_size=source.image.size,
              method='api',model=settings.model)
    problem=settings.problem()
    if problem:return InferenceResult(**base,status='not_configured',error=problem)
    if len(source.png)>10*1024*1024:
        return InferenceResult(**base,status='error',error='标准化 PNG 超过 10 MB，请缩小图片后重新运行两侧方案。')
    taxonomy=rules();prompt=(ROOT/'prompts/classify_v1.txt').read_text(encoding='utf-8')+json.dumps(taxonomy,ensure_ascii=False)
    payload={'model':settings.model,'messages':[{'role':'user','content':[
        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(source.png).decode()}},
        {'type':'text','text':prompt}]}],'max_tokens':settings.max_tokens,'temperature':0.1,'stream':False}
    if settings.provider=='dashscope':payload['enable_thinking']=False
    meta={'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'rules_sha256':fingerprint(taxonomy),
          'endpoint_host':urlparse(settings.base_url).hostname,'sent_image_sha256':source.image_id,'attempts':0}
    error='API 未返回有效结果。'
    # 国内百炼默认直连，避免继承已关闭的本机代理。需要代理的其他服务可显式启用。
    # 不在失败后切换网络重发，以免已经到达服务端的请求重复计费。
    with httpx.Client(timeout=settings.timeout,transport=transport,follow_redirects=False,trust_env=settings.use_env_proxy) as client:
        for attempt in range(settings.max_attempts):
            meta['attempts']=attempt+1
            try:
                response=client.post(settings.base_url+'/chat/completions',headers={'Authorization':'Bearer '+settings.key},json=payload)
                if response.status_code in [429,502,503,504] and attempt+1<settings.max_attempts:
                    sleeper(min(2*(attempt+1),4));continue
                if response.status_code>=300:
                    error={401:'鉴权失败，请核对本地密钥和地域。',403:'接口拒绝访问，请核对模型开通及业务空间权限。',429:'请求限流或额度不足。'}.get(response.status_code,f'API 请求失败（HTTP {response.status_code}），请检查端点、模型及余额。')
                    meta['http_status']=response.status_code;break
                data=response.json()
                # 即使后续结构校验失败，也保留服务端用量：无效输出可能已经计费。
                meta.update(response_id=str(data.get('id','')),returned_model=str(data.get('model',settings.model)),
                            usage=data.get('usage',{}))
                choice=data['choices'][0]
                if choice.get('finish_reason')=='length':raise ValueError('模型输出被截断，请缩小任务范围或增加输出上限。')
                text=choice['message']['content'];items=parse_response(text)
                meta.update(response_id=str(data.get('id','')),returned_model=str(data.get('model',settings.model)),
                            usage=data.get('usage',{}),response_text=text)
                return InferenceResult(**base,status='success',items=items,elapsed_seconds=time.perf_counter()-started,metadata=meta)
            except httpx.TimeoutException:
                error='API 超时。为避免重复计费，没有自动重新提交；可查看服务商账单后手动重试。';break
            except httpx.RequestError:
                error='无法连接 API，请检查网络与 HTTPS 端点。';break
            except (ValueError,ValidationError,KeyError,IndexError,TypeError):
                error='API 返回了无效、截断或不符合约定的 JSON；未把它当作识别成功。';break
    return InferenceResult(**base,status='error',error=error,elapsed_seconds=time.perf_counter()-started,metadata=meta)
