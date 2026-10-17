"""图片上传边界：解码、EXIF 方向校正及统一输入，由网页和 CLI 调用。"""
from dataclasses import dataclass
import hashlib
from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 24_000_000
ALLOWED = {"JPEG", "PNG", "WEBP"}

@dataclass
class ImageInput:
    """同图比较的输入；两方案使用同一张经方向校正的 RGB 原图。"""
    image: Image.Image
    png: bytes
    image_id: str
    source_sha256: str

def decode_image(data: bytes) -> ImageInput:
    """检查真实格式和解压尺寸，返回 RGB 图片；无效文件抛出 ValueError。"""
    if not data or len(data) > MAX_BYTES:
        raise ValueError("请上传非空且不超过 12 MB 的图片。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                if probe.format not in ALLOWED:
                    raise ValueError("仅支持 JPG、PNG 和 WebP 格式。")
                if probe.width * probe.height > MAX_PIXELS:
                    raise ValueError("图片超过 2400 万像素，请先缩小。")
                probe.verify()
            with Image.open(BytesIO(data)) as source:
                oriented = ImageOps.exif_transpose(source)
                # 透明背景合成到白色，避免黑底改变物品外观。
                rgba = oriented.convert("RGBA")
                canvas = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(canvas, rgba).convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
        return ImageInput(image, png, hashlib.sha256(png).hexdigest(), hashlib.sha256(data).hexdigest())
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("无法读取图片：文件损坏或图像尺寸不安全。") from exc
