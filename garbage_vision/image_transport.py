"""无损上传候选：保留完整像素，只移除JPEG元数据；任何不等价情况退回PNG。"""
from io import BytesIO
from PIL import Image


def strip_jpeg_metadata(data):
    """保留JPEG编码扫描数据，移除所有APP/COM段；支持多扫描，不重新压缩。"""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('Not JPEG')
    output = bytearray(data[:2])
    pos = 2
    while pos < len(data):
        start = pos
        if data[pos] != 255:
            raise ValueError('Malformed JPEG marker')
        while pos < len(data) and data[pos] == 255:
            pos += 1
        if pos >= len(data):
            raise ValueError('Truncated JPEG')
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            output.extend(b'\xff\xd9')
            return bytes(output)  # EOI后的尾部数据也不发送。
        if marker in (0x00,0xD8) or 0xD0 <= marker <= 0xD7:
            raise ValueError('Unexpected standalone JPEG marker')
        if marker == 0x01:
            output.extend(data[start:pos])
            continue
        if pos+2 > len(data):
            raise ValueError('Truncated JPEG segment')
        length = int.from_bytes(data[pos:pos+2], 'big')
        end = pos+length
        if length < 2 or end > len(data):
            raise ValueError('Invalid JPEG segment length')
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE):
            output.extend(data[start:end])
        pos = end
        if marker == 0xDA:
            scan_start = pos
            while True:
                found = data.find(b'\xff', pos)
                if found < 0:
                    raise ValueError('Unterminated JPEG scan')
                next_pos = found+1
                while next_pos < len(data) and data[next_pos] == 255:
                    next_pos += 1
                if next_pos >= len(data):
                    raise ValueError('Truncated scan marker')
                code = data[next_pos]
                if code == 0 or 0xD0 <= code <= 0xD7:
                    pos = next_pos+1
                    continue
                output.extend(data[scan_start:found])
                pos = found
                break
    raise ValueError('Missing JPEG end marker')


def prepare_lossless_upload(original, source):
    """逐像素验证压缩格式与两侧共同RGB图等价；不裁剪、不降采样、不有损重编码。"""
    if original.startswith(b'\xff\xd8'):
        try:
            candidate = strip_jpeg_metadata(original)
            with Image.open(BytesIO(candidate)) as decoded:
                decoded.load()
                rgb = decoded.convert('RGB')
                if rgb.size == source.image.size and rgb.tobytes() == source.image.tobytes() and len(candidate) < len(source.png):
                    return candidate, 'image/jpeg', 'original_jpeg_pixel_equivalent_metadata_removed'
        except (ValueError, OSError):
            pass
    # 新建像素图避免继承任何文本或EXIF元数据。
    buffer = BytesIO()
    Image.frombytes('RGB', source.image.size, source.image.tobytes()).save(buffer,format='PNG',optimize=True)
    png = buffer.getvalue()
    return (png if len(png)<len(source.png) else source.png), 'image/png', 'canonical_png'
