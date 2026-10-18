"""仅验证协议和费用边界的替身测试；不代表真实 GPT-6 Astra 的识别效果。"""
import base64
import json
from unittest.mock import patch
import httpx
import pytest
from garbage_vision.api import APISettings,api_settings,infer_api
from garbage_vision.images import decode_image
from test_images_and_app import make_image


def config(**kwargs):
    return APISettings(provider='openai',model='gpt-6-astra',key='test-only',
        base_url='https://api.openai.com/v1',enabled=True,**kwargs)


def response(status='completed',content=None):
    return {'id':'TEST-ONLY','model':'gpt-6-astra','status':status,
        'usage':{'input_tokens':100,'output_tokens':120,'output_tokens_details':{'reasoning_tokens':80}},
        'output':[{'type':'reasoning'}, {'type':'message','content':content or [
            {'type':'output_text','text':'{"items":[{"name":"瓶","category":"recyclable","reason":"测试依据","uncertain":false}]}'}]}]}


def test_responses_contract_and_complete_original_image():
    source=decode_image(make_image());calls=[]
    def handler(request):
        calls.append(request);payload=json.loads(request.content)
        assert request.url.path=='/v1/responses'
        assert payload['model']=='gpt-6-astra' and payload['store'] is False
        assert 'temperature' not in payload and 'messages' not in payload
        assert payload['text']['format']['strict'] is True
        content=payload['input'][0]['content']
        assert base64.b64decode(content[0]['image_url'].split(',')[1])==source.png
        assert not any(term in content[1]['text'] for term in ['local_predictions',source.source_sha256])
        return httpx.Response(200,json=response())
    r=infer_api(source,config(),httpx.MockTransport(handler))
    assert len(calls)==1 and r.status=='success' and r.categories=={'recyclable'}
    assert r.metadata['usage']['output_tokens']==120
    assert r.metadata['sent_image_sha256']==source.image_id


@pytest.mark.parametrize('data',[
    response('incomplete'),response(content=[{'type':'refusal','refusal':'TEST refusal'}]),
    response(content=[{'type':'output_text','text':'{"items":['}]),
])
def test_unfinished_refused_invalid_retains_usage_without_success(data):
    calls=[]
    def handler(request):calls.append(1);return httpx.Response(200,json=data)
    r=infer_api(decode_image(make_image()),config(),httpx.MockTransport(handler))
    assert r.status=='error' and not r.items and len(calls)==1
    assert r.metadata['usage']['output_tokens']==120


def test_openai_never_retries_even_if_legacy_attempts_set():
    calls=[]
    def handler(request):calls.append(1);return httpx.Response(429)
    r=infer_api(decode_image(make_image()),config(max_attempts=2),httpx.MockTransport(handler))
    assert len(calls)==1 and r.metadata['http_status']==429


def test_provider_secrets_are_separate_and_official_host_is_required():
    with patch('garbage_vision.api.dotenv_values',return_value={
        'GV_API_PROVIDER':'openai','GV_API_KEY':'BAILIAN-SECRET','GV_API_MODEL':'qwen3-vl-plus',
        'OPENAI_API_KEY':'OPENAI-SECRET'}),patch.dict('os.environ',{},clear=True):
        s=api_settings()
    assert s.key=='OPENAI-SECRET' and s.model=='gpt-6-astra'
    assert 'SECRET' not in repr(s)
    s.enabled=True;s.base_url='https://untrusted.invalid/v1'
    def handler(request):raise AssertionError('Must not send credentials to another host')
    assert infer_api(decode_image(make_image()),s,httpx.MockTransport(handler)).status=='not_configured'


def test_trial_budget_uses_dollars_and_includes_reasoning_output():
    from scripts.openai_trial import estimated_usd,reservation_usd
    assert estimated_usd({'input_tokens':1000,'output_tokens':2048})==pytest.approx(.1149)
    assert estimated_usd({}) is None
    assert reservation_usd(decode_image(make_image()),config())<.25
    with pytest.raises(ValueError):reservation_usd(decode_image(make_image()),config(image_detail='original'))


def test_nexavlinks_uses_confirmed_chat_endpoint_and_own_currency():
    from scripts.nexavlinks_trial import reservation_nex,estimate_nex
    source=decode_image(make_image());calls=[]
    s=APISettings(provider='nexavlinks',model='gpt-6-astra',base_url='https://www.nexavlinks.com/v1',
                  key='TEST-GATEWAY-KEY',enabled=True,max_attempts=2)
    def handler(request):
        calls.append(request);body=json.loads(request.content)
        assert request.url.host=='www.nexavlinks.com' and request.url.path=='/v1/chat/completions'
        assert body['max_completion_tokens']==2048 and body['reasoning_effort']=='low'
        assert 'temperature' not in body and 'max_tokens' not in body
        assert base64.b64decode(body['messages'][0]['content'][0]['image_url']['url'].split(',')[1])==source.png
        assert body['response_format']['json_schema']['strict'] is True
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}],
            'usage':{'prompt_tokens':100,'completion_tokens':200}})
    result=infer_api(source,s,httpx.MockTransport(handler))
    assert result.status=='success' and len(calls)==1
    assert 4*reservation_nex(source,s)<1 and estimate_nex(result.metadata['usage'])==pytest.approx(.01125)
    with pytest.raises(ValueError):
        from scripts.openai_trial import reservation_usd
        # Official-only trial entrypoint separately rejects a gateway provider.
        reservation_nex(source,config())


def test_nexavlinks_config_does_not_reuse_an_official_key():
    with patch('garbage_vision.api.dotenv_values',return_value={
        'GV_API_PROVIDER':'nexavlinks','OPENAI_API_KEY':'OFFICIAL-KEY','NEXAVLINKS_API_KEY':'NEXA-KEY'}),patch.dict('os.environ',{},clear=True):
        s=api_settings()
    assert s.key=='NEXA-KEY' and s.provider=='nexavlinks'
