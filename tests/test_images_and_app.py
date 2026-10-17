"""验证真实图片解码边界与 Streamlit 页面逻辑，不冒充浏览器自动操作。"""
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import Image
from garbage_vision.images import decode_image, MAX_BYTES

def make_image(fmt="PNG", exif=None):
    """生成仅用于软件校验的图片，不参与模型评估。"""
    out=BytesIO()
    Image.new("RGB", (80, 40), "green").save(out, format=fmt, **({"exif":exif} if exif else {}))
    return out.getvalue()

def test_decode_and_stable_identifier():
    data=make_image()
    result=decode_image(data)
    assert result.image.mode=="RGB" and result.image.size==(80,40)
    assert result.image_id==decode_image(data).image_id

@pytest.mark.parametrize("data", [b"", b"not an image", b"x"*(MAX_BYTES+1)], ids=["empty", "corrupt", "too-large"])
def test_invalid_upload_rejected(data):
    with pytest.raises(ValueError):decode_image(data)

def test_actual_format_is_checked():
    with pytest.raises(ValueError,match="仅支持"):decode_image(make_image("GIF"))

def test_exif_is_applied_to_both_dimensions():
    exif=Image.Exif();exif[274]=6
    assert decode_image(make_image("JPEG",exif)).image.size==(40,80)

def test_page_upload_and_invalid_replacement():
    from streamlit.testing.v1 import AppTest
    class Upload:
        def __init__(self,data): self.data=data
        def getvalue(self):return self.data
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/"app.py"))
    with patch("streamlit.file_uploader",return_value=Upload(make_image())):
        at.run()
    assert not at.exception
    assert any("图片标识" in x.value for x in at.caption)
    with patch("streamlit.file_uploader",return_value=Upload(b"broken")):
        at.run()
    assert not at.exception
    assert any("无法读取" in x.value for x in at.error)
    assert not any("图片标识" in x.value for x in at.caption)
