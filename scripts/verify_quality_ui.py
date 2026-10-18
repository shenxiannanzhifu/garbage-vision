"""真实 GPU 经过页面逻辑的灯和整图回归；不请求 API，不冒充浏览器截图。"""
import json
import os
import tempfile
import uuid
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# 仅用于本工作区Windows沙箱的临时目录兼容；不改变系统ACL。
if os.environ.get('CODEX_TEST_TMP'):
    temporary_root=Path(os.environ['CODEX_TEST_TMP']);temporary_root.mkdir(parents=True,exist_ok=True)
    def inherited_mkdtemp(suffix=None,prefix=None,dir=None):
        path=Path(dir or temporary_root)/f"{prefix or 'tmp'}{uuid.uuid4().hex}{suffix or ''}"
        path.mkdir();return str(path)
    tempfile.mkdtemp=inherited_mkdtemp
from streamlit.testing.v1 import AppTest
from garbage_vision.config import ROOT
from garbage_vision.exports import annotate
from garbage_vision.images import decode_image


def main():
    rows=json.loads((ROOT/'data/manifests/quality_dev.json').read_text(encoding='utf-8'))
    out=ROOT/'evidence/v0.5.0/ui-regression';out.mkdir(parents=True,exist_ok=True)
    class Upload:
        def __init__(self,data):self.data=data
        def getvalue(self):return self.data
    at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=120)
    for key,category,fallback in [('commons-701056','hazardous',False),('commons-26461093','kitchen',True)]:
        row=next(r for r in rows if r['id']==key);raw=(ROOT/row['path']).read_bytes()
        with patch('streamlit.file_uploader',return_value=Upload(raw)):
            at.run();at.button(key='run').click().run()
        assert not at.exception
        result=at.session_state['results']['local']
        assert result.status=='success' and category in result.categories
        assert result.metadata['image_fallback_used']==fallback
        assert 'api' not in at.session_state['results']
        if fallback:
            assert any('未获得可靠定位' in m.value for m in at.info)
            assert any(x.category==category and x.bbox is None for x in result.items)
        else:assert any(x.category==category and x.bbox is not None for x in result.items)
        (out/(key+'.json')).write_text(result.model_dump_json(indent=2),encoding='utf-8')
        (out/(key+'.png')).write_bytes(annotate(decode_image(raw),result))
        print(key,'PASS',sorted(result.categories),'image_fallback',fallback,flush=True)


if __name__=='__main__':main()
