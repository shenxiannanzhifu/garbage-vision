"""检查无损传输的像素、元数据、方向与异常边界，不证明真实API质量。"""
import base64
from io import BytesIO
import json
import random
from PIL import Image
import httpx
import pytest
from garbage_vision.api import APISettings, infer_api
from garbage_vision.images import decode_image
from garbage_vision.image_transport import prepare_lossless_upload, strip_jpeg_metadata


def jpeg(orientation=1, progressive=False):
    image=Image.frombytes('RGB',(180,120),random.Random(42).randbytes(180*120*3))
    exif=Image.Exif();exif[274]=orientation;exif[315]='PRIVATE-METADATA-TEST'
    stream=BytesIO();image.save(stream,'JPEG',quality=85,exif=exif,progressive=progressive)
    return stream.getvalue()


@pytest.mark.parametrize('progressive',[False,True])
def test_jpeg_reuses_compressed_pixels_and_strips_metadata(progressive):
    original=jpeg(progressive=progressive)+b'PRIVATE-TRAILER'
    source=decode_image(original)
    data,mime,mode=prepare_lossless_upload(original,source)
    assert mime=='image/jpeg' and len(data)<len(source.png)
    assert b'PRIVATE-' not in data
    with Image.open(BytesIO(data)) as image:
        assert not image.getexif()
        assert image.convert('RGB').tobytes()==source.image.tobytes()


def test_orientation_and_transparency_keep_canonical_pixels():
    original=jpeg(6);source=decode_image(original)
    data,mime,_=prepare_lossless_upload(original,source)
    assert mime=='image/png' and Image.open(BytesIO(data)).size==(120,180)
    assert Image.open(BytesIO(data)).tobytes()==source.image.tobytes()
    out=BytesIO();Image.new('RGBA',(30,20),(255,0,0,0)).save(out,'PNG')
    source=decode_image(out.getvalue());data,mime,_=prepare_lossless_upload(out.getvalue(),source)
    assert Image.open(BytesIO(data)).getpixel((0,0))==(255,255,255)


def test_malformed_jpeg_rejected():
    with pytest.raises(ValueError):strip_jpeg_metadata(b'\xff\xd8\xff\xe1\xff\xff')


def test_optimized_request_has_same_pixels_correct_mime_and_audit():
    source=decode_image(jpeg())
    config=APISettings(provider='nexavlinks',key='TEST-SECRET',model='gpt-6-astra',
        base_url='https://www.nexavlinks.com/v1',enabled=True,image_transport='lossless')
    def handler(request):
        body=json.loads(request.content);url=body['messages'][0]['content'][0]['image_url']['url']
        assert url.startswith('data:image/jpeg;base64,')
        image=Image.open(BytesIO(base64.b64decode(url.split(',')[1])))
        assert image.convert('RGB').tobytes()==source.image.tobytes()
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}],
                                     'usage':{'prompt_tokens':10,'completion_tokens':10}})
    result=infer_api(source,config,httpx.MockTransport(handler))
    assert result.status=='success' and result.metadata['upload_image_mime']=='image/jpeg'
    assert result.metadata['canonical_image_sha256']==source.image_id
    assert result.metadata['sent_image_sha256']!=source.image_id
    def failure(request):raise httpx.WriteTimeout('TEST-SECRET must never be logged',request=request)
    result=infer_api(source,config,httpx.MockTransport(failure))
    assert result.status=='error' and result.metadata['transport_error_type']=='WriteTimeout'
    assert result.metadata['attempts']==1 and 'TEST-SECRET' not in result.model_dump_json()
