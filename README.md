# 识废 · 同图双方案垃圾识别

AI 方向第二阶段考核项目。使用同一图片比较本地目标检测与多模态 API，中文页面显示识别依据与不确定性。

当前为 v0.1.0 开发阶段。模型识别尚未验收，绝不以示例或模拟结果代替真实预测。

## Windows 运行

在本目录打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

安装成功后也可双击 `启动项目.cmd`。页面地址 http://127.0.0.1:8501 ，只绑定本机。
默认 CUDA 12.8 / Python 3.12；无 NVIDIA GPU 可安装时添加 `-Cpu`。

详见 `PROJECT_STATUS.md`、`docs/你需要做的操作.md`。图片不自动上传，只有运行大模型方案才向配置的 API 发送图片。
