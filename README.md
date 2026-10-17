# 识废 · 同图双方案垃圾识别

AI 方向第二阶段考核项目。使用同一图片比较本地目标检测与多模态 API，中文页面显示识别依据与不确定性。

当前基础运行版 v0.1.0 已验收：图片上传、原图预览、格式与大小校验、EXIF 方向校正、明确模型状态。模型识别尚未接入，页面不显示模拟预测。

## Windows 运行

在本目录打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

安装成功后也可双击 `启动项目.cmd`。页面地址 http://127.0.0.1:8501 ，只绑定本机。
默认 CUDA 12.8 / Python 3.12；无 NVIDIA GPU 可安装时添加 `-Cpu`。

详见 `PROJECT_STATUS.md`、`docs/你需要做的操作.md`。图片不自动上传，只有运行大模型方案才向配置的 API 发送图片。

## 已验证环境与版本证据

Windows 11、Python 3.12.14、PyTorch 2.9.1+cu128、RTX 5060 Laptop GPU（7.96 GiB）。`install.ps1` 已实际运行成功；CUDA 矩阵运算成功；7 项图片边界与页面逻辑检查通过。2026-10-17 用户亲自确认浏览器上传预览正常。

验证：`.venv\Scripts\python.exe -m pytest tests -q`。版本验收记录在 `evidence/v0.1.0/acceptance.md`。浏览器自动化被当前执行环境拒绝，因此网页证据明确采用用户手动确认，不声称完成自动浏览器测试。

本仓库采用 AGPL-3.0；数据和模型保留各自的许可证及来源，详见 `docs/资源与规则.md`。权重、原始数据、虚拟环境和登录凭据均不进入 Git。
