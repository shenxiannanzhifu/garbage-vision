"""输出可分享的环境信息，不读取或打印任何 API 密钥。"""
import json
import platform
from pathlib import Path
import subprocess
import sys

def inspect():
    """实际执行 CUDA 矩阵运算，不能仅凭驱动存在就报告 GPU 可用。"""
    import torch
    result = {"python": sys.version, "platform": platform.platform(), "torch": torch.__version__,
              "cuda_runtime": torch.version.cuda, "cuda_available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        result["gpu"] = torch.cuda.get_device_name(0)
        result["vram_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
        try:
            a = torch.ones((32, 32), device="cuda")
            result["cuda_matmul"] = float((a @ a).sum().item())
        except RuntimeError as exc:
            result["cuda_error"] = str(exc)
    return result

if __name__ == "__main__":
    result = inspect()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
