# Windows PowerShell 中文脚本编码修复

日期：2026-10-17。环境：Windows PowerShell 5.1.26100.9168。

触发：用户双击 `登录GitHub.cmd`，PowerShell 报 `UnexpectedToken`、缺少右花括号，中文显示乱码。原因是文件采用无 BOM UTF-8，而 Windows PowerShell 5.1 按系统 ANSI 编码读取脚本。

使用 `[System.Management.Automation.Language.Parser]::ParseFile` 实际复现：

| 文件 | 修复前解析错误数 | 修复后解析错误数 | 修复后前三字节 |
|---|---:|---:|---|
| scripts/github-login.ps1 | 2 | 0 | EF-BB-BF |
| scripts/install.ps1 | 1 | 0 | EF-BB-BF |
| scripts/start.ps1 | 0 | 0 | EF-BB-BF |

全部 ps1 统一为 UTF-8 BOM / CRLF。cmd 为无 BOM 的 ASCII 兼容 UTF-8 / CRLF，并先执行 `chcp 65001`；编辑器与 Git 的行尾规则同步记录。

实际执行（项目根目录）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\github-login.ps1 -Check
```

退出码 0，输出：

```text
gh version 2.102.0 (2026-09-30)
https://github.com/cli/cli/releases/tag/v2.102.0
检查通过：中文脚本可正常运行，GitHub CLI 已就绪。此检查未登录或上传代码。
```

验证范围：实际的 Windows PowerShell 5.1 读取、中文输出和 GitHub CLI 可执行文件。没有伪造登录成功；此模式不会请求设备授权或推送代码。此前未完成的网页、模型和双方案验证仍维持待验收。
