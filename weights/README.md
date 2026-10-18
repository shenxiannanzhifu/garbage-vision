# 本地权重

运行 `python scripts/download_weights.py` 下载并校验：

| 文件 | 来源与用途 | SHA256 |
|---|---|---|
| sam2.1_t.pt | Ultralytics assets v8.3.0 中 SAM2.1 tiny；自动分割。Meta SAM2 源项目采用 Apache-2.0，当前加载代码采用 Ultralytics AGPL-3.0 | 3c1e81ca9b037dd39d70a014ddb9a813d6c4c4e12555420db7eaff31689bd4e3 |
| ViT-B-32.pt | OpenAI CLIP 官方公开权重；区域图文匹配。OpenAI CLIP 项目 MIT，本项目使用的 Ultralytics CLIP 分支 AGPL-3.0 | 40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af |

下载地址固定在脚本中。两者约 432 MB，权重不入 Git。只加载可信来源；自定义 PyTorch 权重可能包含可执行反序列化内容。

本地模型没有针对本项目微调。YOLO-World s/l 及 YOLOE 候选的开发集结果保留在 evidence/v0.2.0 中，但不是当前默认模型；候选额外权重不属于运行必需项。
