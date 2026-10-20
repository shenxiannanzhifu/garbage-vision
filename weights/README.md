# 本地权重

运行 `python scripts/download_weights.py` 下载并校验：

| 文件 | 来源与用途 | SHA256 |
|---|---|---|
| sam2.1_t.pt | Ultralytics assets v8.3.0 中 SAM2.1 tiny；自动分割。Meta SAM2 源项目采用 Apache-2.0，当前加载代码采用 Ultralytics AGPL-3.0 | 3c1e81ca9b037dd39d70a014ddb9a813d6c4c4e12555420db7eaff31689bd4e3 |
| ViT-B-32.pt | OpenAI CLIP 官方公开权重；区域图文匹配。OpenAI CLIP 项目 MIT，本项目使用的 Ultralytics CLIP 分支 AGPL-3.0 | 40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af |

下载地址固定在脚本中。两者约 432 MB，权重不入 Git。只加载可信来源；自定义 PyTorch 权重可能包含可执行反序列化内容。

当前网页默认的 SAM2 与 CLIP 骨干没有针对本项目微调。v0.6.0 训练了分类向量但候选退步；v0.7.0 用真实框微调 YOLOv8n 定位器，局部改善但未通过全部替换门槛，均未启用。最新候选保存在 `runs/detection-v07/binary-waste3/weights/best.pt`，SHA-256 `373b67a3feb8e8aed12b2b258c1eab182cd10d2df7df4d83a5e6e99a8382b129`，仅用于本地实验且被 Git 忽略。YOLO-World s/l 及 YOLOE 的更早实验保留在 evidence/v0.2.0 中；候选额外权重不属于运行必需项。
