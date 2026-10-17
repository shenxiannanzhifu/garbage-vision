# GitHub 登录网络排查

日期：2026-10-17。真实登录未完成，未推送代码。

用户截图显示 `Authenticate Git ... Yes` 后已获得设备验证码，随后 POST `https://github.com/login/oauth/access_token` 报 `unexpected EOF`。这说明脚本已能执行，但授权请求连接意外结束；不能仅凭此错误断言是某一协议或代理故障。

现场系统代理为 `127.0.0.1:7897`，已启用。检查中没有读取用户密码或令牌。

实际验证：

- Python HTTPS 访问 `https://github.com/login/device` 返回 200。
- 使用明确无效的设备码探测授权端点，返回 200 / `incorrect_device_code`，说明请求可到达并收到 GitHub 的结构化校验响应。没有取得或使用任何有效设备凭据。
- 两次紧随的无效码探测返回 200 / `slow_down`，符合限流响应；随即停止重复探测。这些结果不代表真实登录成功，也不能证明之前 EOF 的唯一原因。
- 沙箱内使用系统 curl 的 Schannel TLS 后端报 `SEC_E_NO_CREDENTIALS`；没有关闭证书验证，以 Python 的独立 TLS 实现完成上述检查。此沙箱现象不等同于用户截图中的 EOF。

脚本调整：仅为本次进程设置 `GODEBUG=http2client=0`，保留已有其他 Go 配置与 TLS 证书验证；继续使用当前系统的本地代理。增加中文步骤、无需重建仓库的提示及最多三次用户回车发起的重试，每次新验证码均须用户本人在浏览器授权。

验证命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\github-login.ps1 -Check
```

Windows PowerShell 5.1 解析错误数 0；上述命令退出码 0，确认 GitHub CLI 2.102.0 可执行及 HTTP/1.1 兼容配置已生效。这个检查不会登录或推送。

待验证：用户重新运行脚本完成实际授权，检查登录账号与目标私有仓库权限。HTTP/1.1 是兼容性尝试，尚不能宣称已彻底解决网络波动。
