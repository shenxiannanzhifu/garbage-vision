"""历史复评页必须显示中断、保留失败，换图也不能发送请求。"""
from unittest.mock import patch
import pytest
from streamlit.testing.v1 import AppTest
from garbage_vision.config import ROOT
from scripts import report_astra


def test_partial_report_cannot_be_presented_as_complete():
    with patch('sys.argv',['report_astra.py']), pytest.raises(ValueError,match='Incomplete evaluation'):
        report_astra.main()


def test_review_page_keeps_failure_and_changes_image_without_network():
    at = AppTest.from_file(str(ROOT/'pages/1_复评结果.py'), default_timeout=30)
    with patch('httpx.Client.send',side_effect=AssertionError('Review must never use network')):
        at.run()
        assert not at.exception
        assert any('复评中断' in x.value for x in at.warning)
        assert any('无法连接 API' in x.value for x in at.error)
        at.selectbox[0].select('commons-24364551').run()
        assert not at.exception and not at.error
        assert any('厨余垃圾' in x.value for x in at.markdown)
        at.selectbox[0].select('commons-128095601').run()
        assert not at.exception and any('无法连接 API' in x.value for x in at.error)
