# 远端同步记录

2026-10-17，用户明确授权将代码与真实历史同步至私有仓库 `shenxiannanzhifu/garbage-vision` 的 `main` 分支，后续验证后的版本持续同步。

已实际推送 `main` 与 `v0.1.0`，未强制推送。GitHub API 返回 main 提交：`15fed084ce444f65df2a98543d416babf6b79e91`，与本地验收提交一致。

第一次推送的 Git shell 凭据助手因 Windows signal pipe 权限失败；随后使用进程内认证完成普通 Git 推送，未将凭据写入源码、命令参数或日志。原始数据、权重、虚拟环境和本地登录配置均未入库。
