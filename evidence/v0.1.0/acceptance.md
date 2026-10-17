# v0.1.0 基础运行版验收

完成日期：2026-10-17（Asia/Shanghai）。当前版本只完成基础运行，不包含已验证垃圾识别。

## 功能与验证

| 内容 | 实际结果 | 证据 |
|---|---|---|
| Windows 安装脚本 | PowerShell 5.1 实际执行成功，退出码 0 | install-check.txt |
| GPU | torch 2.9.1+cu128，RTX 5060 Laptop，矩阵运算结果 32768 | environment.json |
| 登录与仓库 | 账号 shenxiannanzhifu，私有空仓库，ADMIN 权限 | github-access.json |
| 页面服务 | scripts/start.ps1 启动，127.0.0.1:8501 健康检查 ok | 本次运行记录 |
| 图像和页面逻辑 | 7 passed，覆盖空文件、损坏、超限、真实格式、EXIF、上传后切换到损坏图 | software-check.txt、tests/test_images_and_app.py |
| 浏览器实际上传 | 用户打开本地页面上传 JPG/PNG，明确回复“原图和提示都正常” | 本对话用户验收回复（不是自动化截图） |
| 模型与数据可行性 | 已核实候选局限，排除两类通用垃圾权重和含警示牌的数据，准备 YOLO-World 和 Commons 逐图许可路线 | docs/资源与规则.md |

自动浏览器验证限制：Playwright 无法启动 Edge；后续启动后台 Edge 的操作被自动审批拒绝，所需进程启动审批在本会话关闭。应用内部测试用 UploadedFile 边界替身驱动实际页面逻辑，没有冒充浏览器上传。真实网页验收由用户完成。

Git：提交后以 `git show v0.1.0 --stat`、`git log --oneline --decorate` 查实际提交和标签；不在提交生成前伪填其自身哈希。本版验收时未同步远端，等待首次推送确认。

待后续：真实多物品检测与四类覆盖、大模型配置和联调、正式同图比较、报告视频与用户个人感悟。没有创建 v0.2.0 或正式 v1.0.0 标签。
