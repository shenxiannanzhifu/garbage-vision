"""结构、API 边界、数据隔离与真实网页链路检查；网络替身不作为识别证据。"""
import base64
import json
import os
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from garbage_vision.api import APISettings,infer_api,parse_response
from garbage_vision.config import ROOT,rules,local_settings
from garbage_vision.images import decode_image
from garbage_vision.local import classify_region
from garbage_vision.schema import Item,InferenceResult
from garbage_vision.exports import export_csv,annotate
from test_images_and_app import make_image

def test_unknown_is_not_other():
    tax=rules();settings=local_settings();scores=[.1]*(len(tax['items'])+len(tax['background_labels']))
    scores[13]=.6
    assert classify_region(scores,tax,settings).category is None
    scores[-1]=.8
    assert classify_region(scores,tax,settings) is None

@pytest.mark.parametrize('raw',[
    '{"items":[{"name":"瓶","category":"可回收物","reason":"测试","uncertain":false}]}',
    '{"items":[{"name":"瓶","category":"other","reason":"测试","uncertain":true}]}',
    '{"items":[{"name":"瓶","category":"recyclable","reason":"测试","uncertain":false,"confidence":0.9}]}',
    '{"items":[]',
],ids=['bad-enum','contradictory-unknown','invented-confidence','truncated'])
def test_api_rejects_bad_structure(raw):
    with pytest.raises(ValueError):parse_response(raw)

def test_api_same_image_bounded_retry_and_no_local_predictions():
    source=decode_image(make_image());calls=[]
    config=APISettings(key='test-only-key',base_url='https://example.invalid/v1',enabled=True)
    def handler(request):
        data=json.loads(request.content);calls.append(data)
        image=data['messages'][0]['content'][0]['image_url']['url'].split(',')[1]
        assert base64.b64decode(image)==source.png
        assert 'local_predictions' not in json.dumps(data)
        if len(calls)==1:return httpx.Response(429)
        return httpx.Response(200,json={'id':'TEST-ONLY','choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}],'usage':{'prompt_tokens':10,'completion_tokens':5}})
    result=infer_api(source,config,httpx.MockTransport(handler),sleeper=lambda _:None)
    assert result.status=='success' and len(calls)==2 and result.image_id==source.image_id
    assert 'test-only-key' not in result.model_dump_json()

def test_api_timeout_not_retried():
    calls=[]
    def handler(request):calls.append(1);raise httpx.ReadTimeout('TEST timeout')
    result=infer_api(decode_image(make_image()),APISettings(key='test',base_url='https://example.invalid/v1',enabled=True),httpx.MockTransport(handler))
    assert result.status=='error' and len(calls)==1

def test_unconfigured_api_does_not_request():
    def handler(request):raise AssertionError('unconfigured must not call')
    result=infer_api(decode_image(make_image()),APISettings(),httpx.MockTransport(handler))
    assert result.status=='not_configured'

def test_exports_protect_formula_and_wrong_image():
    src=decode_image(make_image())
    result=InferenceResult(image_id=src.image_id,source_sha256=src.source_sha256,image_size=src.image.size,
        method='api',model='TEST',status='success',items=[Item(name='=HYPERLINK("x")',reason='测试',category=None)])
    assert "'=HYPERLINK" in export_csv([result]).decode('utf-8-sig')
    result.image_id='wrong'
    with pytest.raises(ValueError):annotate(src,result)

def test_frozen_manifest_is_disjoint_and_covers_four_groups():
    dev=json.loads((ROOT/'data/manifests/dev.json').read_text(encoding='utf-8'))
    test=json.loads((ROOT/'data/manifests/test.json').read_text(encoding='utf-8'))
    for field in ['sha256','group_id','id']:
        assert not ({x[field] for x in dev}&{x[field] for x in test})
    for rows in [dev,test]:
        assert {c for row in rows for c in row['categories']}==set(rules()['categories'])
        assert all(row['reviewed_before_inference'] and row['review_status']=='accepted' for row in rows)

@pytest.mark.skipif(os.environ.get('RUN_REAL_LOCAL')!='1',reason='需要本地模型权重与开发图片的真实集成检查')
def test_real_page_run_and_image_replacement():
    from streamlit.testing.v1 import AppTest
    class Upload:
        def __init__(self,data):self.data=data
        def getvalue(self):return self.data
    raw=(ROOT/'data/raw/commons/commons-179028310.jpg').read_bytes()
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=120)
    with patch('streamlit.file_uploader',return_value=Upload(raw)):
        at.run();at.button(key='run').click().run()
    assert not at.exception
    result=at.session_state['results']['local']
    assert result.status=='success' and 'recyclable' in result.categories
    assert result.image_id==decode_image(raw).image_id
    with patch('streamlit.file_uploader',return_value=Upload(make_image())):at.run()
    assert not at.exception and at.session_state['results']=={}
    with patch('streamlit.file_uploader',return_value=Upload(b'bad')):at.run()
    assert not at.exception and at.session_state['results']=={} and at.error
