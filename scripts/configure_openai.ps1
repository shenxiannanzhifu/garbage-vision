# 本地密钥配置窗口；不联网、不调用模型、不打印密钥。
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$projectRoot = Split-Path -Parent $PSScriptRoot
$configFile = Join-Path $projectRoot '.env'
$form = New-Object System.Windows.Forms.Form
$form.Text = '垃圾识别项目 · OpenAI 本地配置'
$form.Size = New-Object System.Drawing.Size(580,330)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI',10)
$label = New-Object System.Windows.Forms.Label
$label.Location = New-Object System.Drawing.Point(22,20)
$label.Size = New-Object System.Drawing.Size(530,65)
$label.Text = "请粘贴你自己的 OpenAI API 密钥。`n模型：gpt-6-astra。这里只保存到本机，不调用、不扣费。"
$form.Controls.Add($label)
$inputBox = New-Object System.Windows.Forms.TextBox
$inputBox.Location = New-Object System.Drawing.Point(24,92)
$inputBox.Size = New-Object System.Drawing.Size(515,30)
$inputBox.UseSystemPasswordChar = $true
$form.Controls.Add($inputBox)
$save = New-Object System.Windows.Forms.Button
$save.Text = '保存到本机'
$save.Location = New-Object System.Drawing.Point(24,143)
$save.Size = New-Object System.Drawing.Size(150,38)
$form.Controls.Add($save)
$status = New-Object System.Windows.Forms.Label
$status.Location = New-Object System.Drawing.Point(24,198)
$status.Size = New-Object System.Drawing.Size(515,72)
$status.Text = '不要把密钥发到聊天。保存成功后关闭窗口，回复“已保存”。'
$form.Controls.Add($status)
$save.Add_Click({
    $localKey = $inputBox.Text.Trim()
    if ($localKey.Length -lt 20 -or $localKey -match '\s|["''#]') {
        $status.Text = '密钥似乎不完整或含空格，请重新从 OpenAI API 平台复制。'
        return
    }
    try {
        if (-not (Test-Path -LiteralPath $configFile)) {
            Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $configFile
        }
        $content = [System.IO.File]::ReadAllText($configFile)
        $entries = @{'GV_API_PROVIDER'='openai';'OPENAI_API_KEY'=$localKey;'OPENAI_API_ENABLED'='false'}
        foreach ($name in $entries.Keys) {
            $line = $name + '=' + $entries[$name]
            $pattern = '(?m)^' + [regex]::Escape($name) + '=[^\r\n]*'
            if ([regex]::IsMatch($content,$pattern)) {
                $content = [regex]::Replace($content,$pattern,[System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line })
            } else { $content += "`r`n" + $line + "`r`n" }
        }
        [System.IO.File]::WriteAllText($configFile,$content,(New-Object System.Text.UTF8Encoding($false)))
        $inputBox.Clear()
        $localKey = $null
        $save.Enabled = $false
        $status.Text = '已保存到本机。尚未调用模型，也未扣费。请关闭窗口并回复“已保存”。'
        $status.ForeColor = [System.Drawing.Color]::DarkGreen
    } catch {
        $status.Text = '保存失败，请关闭窗口并告诉助手“配置窗口保存失败”。不要发送密钥。'
    }
})
[void]$form.ShowDialog()
