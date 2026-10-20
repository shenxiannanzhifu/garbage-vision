# 识废 · 同图双方案垃圾识别

AI 方向第二阶段考核项目：中文网页比较同一图片的 **SAM2.1 分割 + CLIP 区域分类** 和 **可配置的多模态图像理解 API**，展示北京生活垃圾四分类、依据与不确定项。

2026-10-20：本次模型优化对比已收尾，进入本人操作、个人感悟与录屏阶段。历史Commons25图：原默认20/25、定位训练22/25、补漏23/25；历史TACO29图：14/29、21/29、21/29。另完成4个历史案例的真实GPU重跑，恢复2个漏检，仍有混合类别遗漏。候选未通过全部回归条件，且没有新的独立留出测试，**网页继续SAM2+CLIP默认方案**。

先看[模型对比与收尾说明](docs/模型对比与收尾说明.md)，再按[你需要做的操作](docs/你需要做的操作.md)完成个人部分。多模态历史尝试38图、33成功、5通信失败；同38图本地32/38、API28/38，成功同33图均28/33。当前不新增付费请求，网页可查看明确标注的历史实测；本轮对比不保证远端连接稳定。

当前尚未完成个人感悟、实际视频和最终提交。旧发布证据保留历史意义，旧候选源码包不含本轮更新。

## Windows 运行

在项目目录打开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install.ps1
.venv\Scripts\python.exe scripts/download_data.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

安装后可双击 `启动项目.cmd`，访问 http://127.0.0.1:8501 。选择上传图片或开发样例，点击“开始识别”。默认只运行本地；勾选大模型会向服务商发送当前图片并可能收费。

安装器建立 Python 3.12 环境、安装 CUDA 12.8 PyTorch、固定版本 CLIP 源码和依赖、下载校验约 432 MB 权重。无 NVIDIA GPU 可增加 `-Cpu`；CPU 性能尚未实测。实测环境为 Windows 11、Python 3.12.14、torch 2.9.1+cu128、RTX 5060 Laptop GPU 7.96 GiB。

## 配置与输出

- 当前NexaVLinks配置已在本机完成，使用独立 `NEXAVLINKS_API_KEY`；官方OpenAI和百炼字段保留且不混用。详见 [NexaVLinks接入与验证](docs/NexaVLinks接入与验证.md)。网页手动调用已恢复，默认不勾选大模型；由用户勾选并点击“开始识别”后发送图片，可能计费，不自动重试。四张样例也可查看已保存实测（不收费）。批量评估仍保持停止。
- `config/local_model.json`：设备和阈值；`config/categories.json`：分类映射；`prompts/classify_v2.txt`：API 提示词。
- 输入 JPG/PNG/WebP，最大 12 MB / 2400 万像素。EXIF 校正、透明区域合成白底后统一 RGB。两侧记录同一图片哈希，API 不接收本地预测。
- 支持 JSON、CSV 和本地标注图。SAM 掩膜质量与 CLIP 余弦相似度均不是分类准确率；API 不编造框和置信度。

单图命令：`.venv\Scripts\python.exe scripts/infer.py data/raw/commons/commons-179028310.jpg --output exports/单图`。

## 验证与局限

`evidence/v0.2.0/local-dev-crops/predictions.json` 保存历史 19 张开发图输出。四类均有成功样例，但漏识别、背景误检、物体局部分割明显，不能精确计数。开发集结果不是测试准确率。真实分类层与定位训练另见本页顶部；二值物品定位有mAP报告，不能等同四分类准确率。见 [模型选择与限制](docs/模型选择与限制.md)。

旧数据为19开发/21测试；本轮新增质量划分为38开发（含原19张）/40新测试。每图有来源/许可/哈希，并按作者分组及查重。标签来自作者元数据与 Codex 视觉复核，非独立真人标注；多类别混合与未知场景仍不足。见 [数据与分类规则](docs/数据与分类规则.md)。

2026-10-18 历史候选版完成隔离环境安装验证；2026-10-20最新86项检查通过（24.62秒），含真实GPU推理经过Streamlit AppTest、换图/坏图清理、历史复评页、无损上传、预算边界、训练梯度、数据泄漏防护和补漏边界。AppTest 不等于浏览器截图/录屏。用户已完成 v0.2 本地标注图和 v0.3 双侧结果/JSON 导出的实际浏览器验收。

```powershell
$env:RUN_REAL_LOCAL='1'
$env:CODEX_TEST_TMP=Join-Path (Get-Location) '.local/test-temp'
.venv\Scripts\python.exe -m pytest tests -q
```

API 成功证据为 `evidence/v0.3.0/api-probe-20261018T075101382996Z/result.json`。一次成功不能代表整体准确率。免费额度和账单以百炼控制台为准。

## 故障与材料

缺权重时运行 `scripts/download_weights.py`；北京 API 默认直连，其他服务需要环境代理时才设 `GV_API_USE_ENV_PROXY=true`。鉴权失败核对密钥地域和模型权限。无识别框可能是低相似度、遮挡或小目标，不代表图片没有垃圾。

保持 `.ps1` 的 UTF-8 BOM 和 `.cmd` 的 CRLF。进度见 [PROJECT_STATUS](PROJECT_STATUS.md)，个人操作见 [你需要做的操作](docs/你需要做的操作.md)。代码为 AGPL-3.0，模型和数据保留各自许可；权重、原图、环境和密钥不入 Git。


## 历史 v0.4.0 双方案评估（不代表当前版本）

同一冻结测试集 21 张，逐图平均 F1：本地 **0.6032**，API **0.8571**。API 3 条无效结构响应均计零且没有重试；集合完全一致分别为 10/21、18/21。数据量小、标签非独立真人标注，不能外推实际投放准确率。

[完整报告](evidence/v0.4.0/final-test/report/对比报告.md) · [错误案例分析](docs/错误案例分析.md) · [项目说明与个人感悟](docs/项目说明与个人感悟.md) · [代码导览](docs/代码导览与答辩.md) · [录制说明](docs/演示录制说明.md) · [验收清单](docs/验收清单.md)。

只重算已有结果和生成报告，不收费：

```powershell
.venv\Scripts\python.exe scripts/generate_report.py evidence/v0.4.0/final-test
```

如需要重新执行模型评估，应新建实验目录，冻结当前干净提交，重新确认 API 预算；不可覆盖已有逐图证据。精确复现本次推理代码可检出 freeze.json 中记录的 3442a3f；源码哈希容忍 CRLF/LF，数据和权重仍按原始字节校验。JSON 中始终保留原始输出，不用图表代替原始记录。

历史候选交付的隔离环境复现记录见 [复现记录](evidence/v1.0.0-rc.1/reproducibility.md)：全新 venv 安装、31 项检查及实际启动通过。本轮已按实际38图及中断状态收尾；当前还需本人个人感悟、理解自查和视频。正式 v1.0.0 尚未创建。
