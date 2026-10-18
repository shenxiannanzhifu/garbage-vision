"""验证已存真实记录回显不会触发收费、不会用在另一张图片。"""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from garbage_vision.api import APISettings
from garbage_vision.config import ROOT
from garbage_vision.images import decode_image
from garbage_vision.saved_results import find_saved_api
from test_images_and_app import make_image


def test_saved_actual_result_matches_source_and_provider():
    source=decode_image((ROOT/'data/raw/commons/commons-701056.jpg').read_bytes())
    config=APISettings(provider='nexavlinks',model='gpt-6-astra')
    result=find_saved_api(source,config)
    assert result and result.categories=={'hazardous'}
    assert result.metadata['display_mode']=='saved_real_api_result'
    assert find_saved_api(decode_image(make_image()),config) is None
    assert find_saved_api(source,APISettings(provider='openai',model='gpt-6-astra')) is None


def test_page_saved_actual_api_result_never_makes_network_call():
    class Upload:
        def getvalue(self):return (ROOT/'data/raw/commons/commons-701056.jpg').read_bytes()
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
    with patch('streamlit.file_uploader',return_value=Upload()),patch('garbage_vision.api.api_settings',
            return_value=APISettings(provider='nexavlinks',model='gpt-6-astra')),patch('garbage_vision.api.infer_api',
            side_effect=AssertionError('Saved display must not call the API')):
        at.run();at.button(key='saved_api').click().run()
    assert not at.exception and at.session_state['results']['api'].categories=={'hazardous'}
    assert any('本次没有发送请求' in x.value for x in at.info)
