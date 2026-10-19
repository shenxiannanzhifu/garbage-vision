"""网页手动调用边界的软件测试；所有推理替身均禁止联网，不算识别成绩。"""
from dataclasses import replace
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from garbage_vision.api import APISettings
from garbage_vision.config import ROOT
from garbage_vision.images import decode_image
from garbage_vision.schema import InferenceResult
from test_images_and_app import make_image


SETTINGS=APISettings(provider='nexavlinks',model='gpt-6-astra',key='SOFTWARE_TEST_ONLY',
    base_url='https://www.nexavlinks.com/v1',enabled=True)


class Upload:
    def getvalue(self):return make_image()


def test_configured_but_paused_is_not_presented_as_missing_key():
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
    with patch('streamlit.file_uploader',return_value=Upload()), \
         patch('garbage_vision.api.api_settings',return_value=replace(SETTINGS,enabled=False)), \
         patch('httpx.Client.send',side_effect=AssertionError('No network in UI test')):
        at.run()
        assert not at.exception
        assert at.checkbox[0].disabled
        assert any('已完成本地配置' in x.value and '暂停' in x.value for x in at.info)


def test_enabled_api_requires_selection_and_explicit_run_and_does_not_repeat():
    source=decode_image(make_image())
    local=InferenceResult(image_id=source.image_id,source_sha256=source.source_sha256,
        image_size=source.image.size,method='local',model='SOFTWARE_TEST_ONLY',status='success',
        metadata={'software_test_double':True})
    api=local.model_copy(update={'method':'api','model':'SOFTWARE_TEST_ONLY'})
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
    with patch('streamlit.file_uploader',return_value=Upload()), \
         patch('garbage_vision.api.api_settings',return_value=SETTINGS), \
         patch('garbage_vision.local.infer_local',return_value=local), \
         patch('garbage_vision.api.infer_api',return_value=api) as infer, \
         patch('httpx.Client.send',side_effect=AssertionError('No network in UI test')):
        at.run()
        assert not at.exception and not at.checkbox[0].disabled and not at.checkbox[0].value
        at.button(key='run').click().run()
        assert not at.exception and infer.call_count==0
        at.checkbox[0].check().run()
        assert not at.exception and infer.call_count==0
        at.button(key='run').click().run()
        assert not at.exception and infer.call_count==1
        at.run()
        assert not at.exception and infer.call_count==1
