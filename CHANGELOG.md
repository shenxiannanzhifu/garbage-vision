# 更新记录

## v0.1.0（开发中，2026-10-17）
- 建立项目隔离环境、Windows 安装与启动入口、中文开发状态和资源核实记录。
- 实现图片真实格式检查、损坏文件处理、像素限制与 EXIF 方向校正。
- 修复 Windows PowerShell 5.1 读取无 BOM 中文脚本时的乱码和语法错误；安装、启动与 GitHub 登录脚本统一 UTF-8 BOM，批处理入口使用 UTF-8 控制台。
- 增加 GitHub 登录入口与无需联网、不会登录或上传的 `-Check` 检查模式；实际 Windows PowerShell 5.1 验证通过，见 `evidence/v0.1.0/powershell-encoding.md`。
- 针对 GitHub 授权请求 `unexpected EOF`，在登录窗口启用 HTTP/1.1 兼容设置，补充中文步骤和最多三次由用户确认的重试；真实授权仍待用户完成，未声称已修复全部网络波动。
