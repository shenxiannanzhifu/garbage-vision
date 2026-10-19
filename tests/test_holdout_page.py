"""历史复评页必须显示中断、保留失败，换图也不能发送请求。"""
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from streamlit.testing.v1 import AppTest
from garbage_vision.config import ROOT
from scripts import report_astra


def test_partial_report_cannot_be_presented_as_complete():
    # 使用缺失预测的临时清单，不依赖真实评估是否已经完成。
    with TemporaryDirectory() as directory:
        folder = Path(directory)
        frozen = (report_astra.DIRECTORY/'freeze.json').read_text(encoding='utf-8')
        (folder/'freeze.json').write_text(frozen,encoding='utf-8')
        with patch.object(report_astra,'DIRECTORY',folder), patch('sys.argv',['report_astra.py']), pytest.raises(ValueError,match='Incomplete evaluation'):
            report_astra.main()


def test_review_page_keeps_failure_and_changes_image_without_network():
    at = AppTest.from_file(str(ROOT/'pages/1_复评结果.py'), default_timeout=30)
    with patch('httpx.Client.send',side_effect=AssertionError('Review must never use network')):
        at.run()
        assert not at.exception
        complete = (report_astra.DIRECTORY/'comparison.json').exists()
        assert any('复评中断' in x.value for x in at.warning) == (not complete)
        assert any('成功返回的同 33 张' in x.value and '28/33' in x.value for x in at.markdown)
        assert any('无法连接 API' in x.value for x in at.error)
        at.selectbox[0].select('commons-24364551').run()
        assert not at.exception and not at.error
        assert any('厨余垃圾' in x.value for x in at.markdown)
        at.selectbox[0].select('commons-128095601').run()
        assert not at.exception and any('无法连接 API' in x.value for x in at.error)
        at.selectbox[0].select('commons-132219783').run()
        assert not at.exception and not at.error
        assert any('质量复核' in x.value and 'Alkaline' in x.value for x in at.warning)
