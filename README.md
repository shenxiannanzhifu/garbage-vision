# 识废 · 同图双方案垃圾识别

AI 方向第二阶段考核项目：中文网页比较同一图片的 **SAM2.1 分割 + CLIP 区域分类** 和 **可配置的多模态图像理解 API**，展示北京生活垃圾四分类、依据与不确定项。

当前进行质量改进。旧 v0.1.0–v0.4.0、v1.0.0-rc.1 证据保留，但不代表当前已经满足最终交付条件。本地模型已升级，NexaVLinks / `gpt-6-astra` 原40图评估目前尝试38张：33次有效响应、5次通信失败、2张未请求。本地/大模型同38图集合匹配32/38、28/38；成功返回的同33图都是28/33。见[复评进度](evidence/v0.5.0/astra-holdout/复评中断进度.md)及[逐图质量复核](evidence/v0.5.0/astra-holdout/质量复核与下一步.md)。尚不能宣称整体质量达标。

同组新40图：本地类别集合完全正确 **26/40 → 33/40**；32张非空类别图平均F1 **0.7552 → 0.8646**；8张未知/背景图误报 **3 → 2**。这些是小规模、非独立真人标注的类别集合指标，不是定位准确率。见[质量复评报告](evidence/v0.5.0/quality-holdout/质量对比报告.md)。

网页侧栏“复评结果”可逐张查看已尝试图片的双侧真实历史记录，不收费。[无损传输候选](docs/多模态效果与效率优化.md)已试2图：荧光灯正确、塑料瓶连接失败后停止；未证明质量或速度提高，默认未开启。当前优先补齐质量评估的类别覆盖，所有通信失败和标注歧义保留。

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

- 当前NexaVLinks配置已在本机完成，使用独立 `NEXAVLINKS_API_KEY`；官方OpenAI和百炼字段保留且不混用。详见 [NexaVLinks接入与验证](docs/NexaVLinks接入与验证.md)。网页新收费调用保持关闭，四张样例可点击“查看本图已保存的大模型实测（不收费）”。
- `config/local_model.json`：设备和阈值；`config/categories.json`：分类映射；`prompts/classify_v2.txt`：API 提示词。
- 输入 JPG/PNG/WebP，最大 12 MB / 2400 万像素。EXIF 校正、透明区域合成白底后统一 RGB。两侧记录同一图片哈希，API 不接收本地预测。
- 支持 JSON、CSV 和本地标注图。SAM 掩膜质量与 CLIP 余弦相似度均不是分类准确率；API 不编造框和置信度。

单图命令：`.venv\Scripts\python.exe scripts/infer.py data/raw/commons/commons-179028310.jpg --output exports/单图`。

## 验证与局限

`evidence/v0.2.0/local-dev-crops/predictions.json` 保存全部 19 张开发图输出。四类均有成功样例，但漏识别、背景误检、物体局部分割明显，不能精确计数。开发集结果不是测试准确率；没有定位真值，未微调或计算 mAP。见 [模型选择与限制](docs/模型选择与限制.md)。

旧数据为19开发/21测试；本轮新增质量划分为38开发（含原19张）/40新测试。每图有来源/许可/哈希，并按作者分组及查重。标签来自作者元数据与 Codex 视觉复核，非独立真人标注；多类别混合与未知场景仍不足。见 [数据与分类规则](docs/数据与分类规则.md)。

2026-10-18 历史候选版完成隔离环境安装验证；当前质量改进与 API 适配版61项检查通过，含真实GPU推理经过Streamlit AppTest、换图/坏图清理、历史复评页、无损上传与预算边界。AppTest 不等于浏览器截图/录屏。用户已完成 v0.2 本地标注图和 v0.3 双侧结果/JSON 导出的实际浏览器验收。

```powershell
$env:RUN_REAL_LOCAL='1'
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

历史候选交付的隔离环境复现记录见 [复现记录](evidence/v1.0.0-rc.1/reproducibility.md)：全新 venv 安装、31 项检查及实际启动通过。当前还需 Astra 新40图同图复评、模型质量复核，以及本人个人感悟和视频。正式 v1.0.0 尚未创建。
