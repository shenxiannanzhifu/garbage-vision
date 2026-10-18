# v0.2.0 验证记录

2026-10-18：实现及 GPU 链路通过，新版浏览器显示待确认，未打 v0.2.0 标签。

- 全部 19 张开发图：local-dev-crops/predictions.json；标注图在忽略目录 data/cache/local-dev-crops。
- 四类均有成功样例，但定位/漏检/背景干扰存在，见 docs/模型选择与限制.md。未训练，无定位真值，无 mAP。
- RUN_REAL_LOCAL=1 下运行 `python -m pytest tests -q -p no:cacheprovider`：18 passed，35.28 秒，记录 software-check.txt。模型真实加载 GPU，只有上传控件传文件的边界使用测试替身。
- 完整 install.ps1 在现有环境重新执行成功，记录 install-check.txt；CLIP 固定源码构建、权重校验、CUDA 运算通过。这不是干净电脑验收。
- 验证换图/坏图清理、未知类别、API 解析/超时、CSV 公式防护、图像 ID 一致性。
- 浏览器自动化曾被环境策略自动拒绝，已有 v0.1 人工上传确认，暂无新版截图或录屏。
