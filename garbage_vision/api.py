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

PROMPT_PATH = 'prompts/classify_v2.txt'

@dataclass
class APISettings:
    """密钥不参与 repr、页面配置展示或导出；只用于 Authorization 请求头。"""
    key: str=field(default='',repr=False)
    base_url: str=''
    model: str='qwen3-vl-plus'
    provider: str='dashscope'
    timeout: float=60
    max_tokens: int=2048
    max_attempts: int=1
    enabled: bool=False
    use_env_proxy: bool=False
    reasoning_effort: str='low'
    image_detail: str='high'

    def problem(self):
        if not self.enabled:return '尚未启用图像理解 API；在本地 .env 中配置后启用。'
        if not self.key or not self.base_url:return '尚未填写 API 密钥或接口地址。'
        parsed=urlparse(self.base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return 'API 地址必须为不含凭据、查询参数的 HTTPS Base URL。'
        if not self.model:return '尚未配置模型名称。'
        if self.provider=='openai':
            if self.base_url!='https://api.openai.com/v1':return 'OpenAI 适配器仅向官方 https://api.openai.com/v1 发送密钥。'
            if self.reasoning_effort not in {'low','medium','high','xhigh','max'}:return 'OpenAI reasoning effort 配置无效。'
            if self.image_detail not in {'low','high','original','auto'}:return 'OpenAI 图片 detail 配置无效。'
        return None

def api_settings():
    """每次读取本地配置，用户保存后无需重启；真实环境变量优先于 .env。"""
    values={**dotenv_values(ROOT/'.env'),**os.environ}
    provider=str(values.get('GV_API_PROVIDER') or 'openai').strip()
    if provider=='openai':
        # OpenAI 使用独立字段，绝不把已有百炼密钥发送到另一个服务商。
        return APISettings(provider='openai',base_url='https://api.openai.com/v1',
            key=str(values.get('OPENAI_API_KEY') or '').strip(),
            model=str(values.get('OPENAI_MODEL') or 'gpt-6-astra').strip(),
            timeout=max(5,min(180,float(values.get('OPENAI_TIMEOUT') or 120))),
            max_tokens=max(256,min(4096,int(values.get('OPENAI_MAX_OUTPUT_TOKENS') or 2048))),
            max_attempts=1,enabled=str(values.get('OPENAI_API_ENABLED') or '').lower()=='true',
            use_env_proxy=str(values.get('OPENAI_USE_ENV_PROXY') or '').lower()=='true',
            reasoning_effort=str(values.get('OPENAI_REASONING_EFFORT') or 'low'),
            image_detail=str(values.get('OPENAI_IMAGE_DETAIL') or 'high'))
    workspace=str(values.get('GV_API_WORKSPACE_ID') or '').strip()
    base=str(values.get('GV_API_BASE_URL') or '').strip().rstrip('/')
    if not base and workspace:
        if not re.fullmatch(r'[A-Za-z0-9-]+',workspace):raise ValueError('业务空间 ID 只能包含字母、数字和连字符。')
        base=f'https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'
    return APISettings(key=str(values.get('GV_API_KEY') or '').strip(),base_url=base,
        provider=provider,model=str(values.get('GV_API_MODEL') or 'qwen3-vl-plus'),
        timeout=max(5,min(180,float(values.get('GV_API_TIMEOUT') or 60))),
        max_tokens=max(256,min(4096,int(values.get('GV_API_MAX_TOKENS') or 2048))),
        max_attempts=max(1,min(2,int(values.get('GV_API_MAX_ATTEMPTS') or 1))),
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


def build_payload(source,settings,prompt):
    """两种协议独立适配；只发送完整 RGB 原图和规则，不发送本地预测。"""
    image_url='data:image/png;base64,'+base64.b64encode(source.png).decode()
    if settings.provider=='openai':
        schema=APIResponse.model_json_schema()
        # 字符串长度在本地校验；请求只使用已核实的 JSON Schema 子集。
        for field_schema in schema['$defs']['APIItem']['properties'].values():
            field_schema.pop('minLength',None);field_schema.pop('maxLength',None)
        return '/responses',{
            'model':settings.model,'store':False,'stream':False,
            'reasoning':{'effort':settings.reasoning_effort},
            'max_output_tokens':settings.max_tokens,
            'input':[{'role':'user','content':[
                {'type':'input_image','image_url':image_url,'detail':settings.image_detail},
                {'type':'input_text','text':prompt}]}],
            'text':{'format':{'type':'json_schema','name':'garbage_items','strict':True,
                             'schema':schema}}}
    payload={'model':settings.model,'messages':[{'role':'user','content':[
        {'type':'image_url','image_url':{'url':image_url}},
        {'type':'text','text':prompt}]}],'max_tokens':settings.max_tokens,'temperature':0.1,'stream':False}
    if settings.provider=='dashscope':payload['enable_thinking']=False
    return '/chat/completions',payload


def extract_response(data,settings,meta):
    """拒绝和截断保留用量但不算成功；Responses 的 reasoning 不当作答案。"""
    if settings.provider=='openai':
        status=data.get('status');meta['finish_reason']=status
        meta['incomplete_details']=data.get('incomplete_details')
        parts=[];refused=False
        for output in data.get('output',[]):
            if output.get('type')!='message':continue
            for part in output.get('content',[]):
                if part.get('type')=='refusal':refused=True
                if part.get('type')=='output_text':parts.append(part['text'])
        text=''.join(parts);meta.update(response_diagnostics(text,settings.key))
        if refused:meta['refused']=True;raise ValueError('模型拒绝回答。')
        if status!='completed':raise ValueError('Responses 输出未完成。')
        if not text:raise ValueError('Responses 没有文本答案。')
        return text
    choice=data['choices'][0];text=choice['message']['content']
    meta.update(response_diagnostics(text,settings.key),finish_reason=choice.get('finish_reason'))
    if choice.get('finish_reason')!='stop':raise ValueError('模型输出未正常完成。')
    return text


def response_diagnostics(text, key):
    """保留可排错的有限响应正文；删除密钥、常见令牌及内联图片，不记录请求头。"""
    if not isinstance(text,str):return {'response_content_type':type(text).__name__}
    safe=text.replace(key,'[REDACTED]') if key else text
    safe=re.sub(r'(?i)\bBearer\s+[^\s"<>]+','Bearer [REDACTED]',safe)
    safe=re.sub(r'\bsk-[A-Za-z0-9_-]{8,}','[REDACTED]',safe)
    safe=re.sub(r'data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+','[IMAGE REDACTED]',safe)
    return {'response_text':safe[:50000],'response_text_truncated':len(safe)>50000,
            'response_text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}

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
    taxonomy=rules();prompt=(ROOT/PROMPT_PATH).read_text(encoding='utf-8')+json.dumps(taxonomy,ensure_ascii=False)
    endpoint,payload=build_payload(source,settings,prompt)
    meta={'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'rules_sha256':fingerprint(taxonomy),
          'endpoint_host':urlparse(settings.base_url).hostname,'sent_image_sha256':source.image_id,'attempts':0,
          'provider':settings.provider,'api_protocol':'responses' if settings.provider=='openai' else 'chat_completions',
          'prompt_path':PROMPT_PATH}
    error='API 未返回有效结果。'
    # 国内百炼默认直连，避免继承已关闭的本机代理。需要代理的其他服务可显式启用。
    # 不在失败后切换网络重发，以免已经到达服务端的请求重复计费。
    with httpx.Client(timeout=settings.timeout,transport=transport,follow_redirects=False,trust_env=settings.use_env_proxy) as client:
        attempts=1 if settings.provider=='openai' else settings.max_attempts
        for attempt in range(attempts):
            meta['attempts']=attempt+1
            try:
                response=client.post(settings.base_url+endpoint,headers={'Authorization':'Bearer '+settings.key},json=payload)
                if response.status_code in [429,502,503,504] and attempt+1<attempts:
                    sleeper(min(2*(attempt+1),4));continue
                if response.status_code>=300:
                    error={401:'鉴权失败，请核对本地密钥和地域。',403:'接口拒绝访问，请核对模型开通及业务空间权限。',429:'请求限流或额度不足。'}.get(response.status_code,f'API 请求失败（HTTP {response.status_code}），请检查端点、模型及余额。')
                    meta['http_status']=response.status_code;break
                data=response.json()
                if not isinstance(data,dict):raise ValueError('API 顶层 JSON 必须为对象。')
                usage=data.get('usage') or {}
                if not isinstance(usage,dict):raise ValueError('API 用量字段无效。')
                # 即使后续结构校验失败，也保留服务端用量：无效输出可能已经计费。
                meta.update(response_id=str(data.get('id','')),returned_model=str(data.get('model',settings.model)),
                            usage=usage)
                text=extract_response(data,settings,meta)
                from .api_normalization import normalize_api_response
                items,audit=normalize_api_response(text)
                meta['normalization']=audit
                return InferenceResult(**base,status='success',items=items,elapsed_seconds=time.perf_counter()-started,metadata=meta)
            except httpx.TimeoutException:
                error='API 超时。为避免重复计费，没有自动重新提交；可查看服务商账单后手动重试。';break
            except httpx.RequestError:
                error='无法连接 API，请检查网络与 HTTPS 端点。';break
            except (ValueError,ValidationError,KeyError,IndexError,TypeError) as exc:
                meta['validation_error_type']=type(exc).__name__
                if isinstance(exc,ValidationError):
                    # 不存 input/context，避免错误信息带出任意响应或凭据。
                    meta['validation_errors']=[{'location':list(e['loc']),'type':e['type']}
                        for e in exc.errors(include_input=False,include_context=False)[:20]]
                error='API 返回了无效、截断或不符合约定的 JSON；未把它当作识别成功。';break
    return InferenceResult(**base,status='error',error=error,elapsed_seconds=time.perf_counter()-started,metadata=meta)
