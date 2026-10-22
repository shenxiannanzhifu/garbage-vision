param([switch]$Gpu, [switch]$Maintenance)
$ErrorActionPreference = 'Stop'
$ProxyUrl = ''
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$DockerExe = Join-Path (Split-Path -Parent $ProjectRoot) 'runtime\docker-app\resources\bin\docker.exe'
if (!(Test-Path -LiteralPath $DockerExe)) { $DockerExe = 'docker' }
$EvidenceRoot = Join-Path $ProjectRoot 'evidence\stage3\linux-container'
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$LogPath = Join-Path $EvidenceRoot 'deploy.log'
$RunId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$ReportPath = Join-Path $EvidenceRoot 'deploy-summary.json'
# 保留此前失败/成功记录；最新运行写入独立报告，不改写历史证据。
if (Test-Path -LiteralPath $ReportPath) {
    $ArchiveRoot = Join-Path $EvidenceRoot 'deploy-history'
    New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null
    Copy-Item -LiteralPath $ReportPath -Destination (Join-Path $ArchiveRoot ($RunId+'-previous.json'))
}
if ($Maintenance) { $ReportPath = Join-Path $EvidenceRoot ('maintenance-'+$RunId+'.json') }
$Report = [ordered]@{started_at=(Get-Date).ToUniversalTime().ToString('o'); mode='cpu'; complete=$false; maintenance=[bool]$Maintenance; checks=@()}
$ProxyBefore = @{}
foreach ($ProxyName in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','GV_S3_API_URL')) {
    $ProxyBefore[$ProxyName] = [Environment]::GetEnvironmentVariable($ProxyName,'Process')
}
$ExitCode = 0
$ComposeArgs = @('compose','-f','compose.yaml')
if ($Gpu) { $ComposeArgs += @('-f','compose.gpu.yaml'); $Report.mode='gpu' }
function Run-Docker {
    param([string]$Name,[string[]]$Arguments)
    Write-Host "执行：$Name"
    $PreviousPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    & $DockerExe @Arguments 2>&1 | ForEach-Object {
        $Line=$_.ToString(); Write-Host $Line
        Add-Content -LiteralPath $LogPath -Value $Line -Encoding UTF8
    }
    $Code=$LASTEXITCODE
    $ErrorActionPreference=$PreviousPreference
    $Report.checks += [ordered]@{name=$Name;exit_code=$Code;passed=($Code -eq 0)}
    $Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    if ($Code -ne 0) { throw "$Name 失败；请把末尾错误发给助手，完整记录保存在D盘。" }
}
try {
    if (!(Test-Path -LiteralPath '.env.stage3')) { throw '缺少.env.stage3，请让助手先准备本机服务配置。' }
    if ($Maintenance) {
        $env:GV_S3_API_URL='http://127.0.0.1:8080/api'
        $MaintenanceRoot = Join-Path $ProjectRoot ('.local\maintenance\'+$RunId)
        & '.venv\Scripts\python.exe' scripts/verify_stage3_maintenance.py snapshot $MaintenanceRoot
        if ($LASTEXITCODE -ne 0) { throw '维护前快照失败，未更改运行服务。' }
        $RollbackTag = 'garbage-vision-stage3:before-'+$RunId
        Run-Docker 'Preserve previous image for rollback' @('tag','garbage-vision-stage3:local',$RollbackTag)
        $Report.rollback_image=$RollbackTag
        $Report.maintenance_dir=$MaintenanceRoot
    }
    # Windows buildx可能在客户端获取镜像令牌，不沿用Desktop界面代理。
    # 只读取当前用户已有代理，并设置本脚本进程；不更改Windows全局配置。
    $WindowsProxy = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
    if ($WindowsProxy.ProxyEnable -eq 1 -and $WindowsProxy.ProxyServer) {
        $ProxyServer = [string]$WindowsProxy.ProxyServer
        if ($ProxyServer -match '(?:^|;)http=([^;]+)') { $ProxyServer = $Matches[1] }
        elseif ($ProxyServer.Contains(';') -or $ProxyServer.Contains('=')) { throw '系统代理格式需单独处理，请把此提示发给助手。' }
        $ProxyUrl = if ($ProxyServer -match '^https?://') { $ProxyServer } else { 'http://' + $ProxyServer }
    }
    if ($ProxyUrl) {
        $ProxyUri = [uri]$ProxyUrl
        if ($ProxyUri.Scheme -notin @('http','https') -or !$ProxyUri.Host -or $ProxyUri.UserInfo) { throw '代理地址格式无效；不要在命令行中填写代理密码。' }
        foreach ($ProxyName in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')) {
            [Environment]::SetEnvironmentVariable($ProxyName,$ProxyUrl,'Process')
        }
        $env:NO_PROXY = 'localhost,127.0.0.1,::1,api,web,nginx,host.docker.internal'
        Write-Host ('构建客户端已使用当前进程代理：{0}:{1}' -f $ProxyUri.Host,$ProxyUri.Port)
        # 令牌响应丢弃，只保留状态码，避免凭据进入日志。
        $ProbeCode = & curl.exe --silent --show-error --proxy $ProxyUrl --connect-timeout 15 --max-time 30 --output NUL --write-out '%{http_code}' 'https://auth.docker.io/token?scope=repository%3Alibrary%2Fpython%3Apull&service=registry.docker.io'
        if ($LASTEXITCODE -ne 0 -or $ProbeCode -ne '200') { throw '当前进程代理无法访问Docker令牌服务；已停止构建，请反馈此错误。' }
        Write-Host 'Docker镜像令牌服务经代理连接通过（HTTP 200，未保存令牌）。'
    }
    New-Item -ItemType Directory -Path '.local\container-data' -Force | Out-Null
    Run-Docker 'Compose configuration validation (no secret output)' ($ComposeArgs+@('config','--quiet'))
    $BuildArgs = @('--progress','plain','build')
    if ($ProxyUrl) {
        # RUN apt/pip位于Linux构建环境，127.0.0.1不是Windows宿主。
        # 使用引擎公布的内部代理入口，不将宿主代理地址硬编码进镜像。
        $EngineProxy = & $DockerExe info --format '{{.HTTPProxy}}'
        if ($LASTEXITCODE -ne 0 -or !$EngineProxy) { throw '未取得Docker引擎内部代理地址，已停止构建；请反馈此提示。' }
        $EngineProxy = ([string]$EngineProxy).Trim()
        if ($EngineProxy -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') { $EngineProxy = 'http://' + $EngineProxy }
        $EngineProxyUri = [uri]$EngineProxy
        if ($EngineProxyUri.Scheme -notin @('http','https') -or !$EngineProxyUri.Host -or $EngineProxyUri.UserInfo) { throw 'Docker引擎代理格式需人工核对；未输出代理凭据。' }
        foreach ($ProxyName in @('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy')) {
            $BuildArgs += @('--build-arg', ($ProxyName+'='+$EngineProxy))
        }
        $BuildArgs += @('--build-arg','NO_PROXY=localhost,127.0.0.1,::1,api,web,nginx',
                        '--build-arg','no_proxy=localhost,127.0.0.1,::1,api,web,nginx')
        Write-Host 'Linux构建步骤将使用Docker引擎内部代理（不写入镜像ENV）。'
    }
    Run-Docker 'Build Linux application image' ($ComposeArgs+$BuildArgs+@('api'))
    if ($Maintenance) {
        Run-Docker 'Stop API before consistent backup' ($ComposeArgs+@('stop','api'))
        try {
            & '.venv\Scripts\python.exe' scripts/verify_stage3_maintenance.py backup $MaintenanceRoot
            if ($LASTEXITCODE -ne 0) { throw '停服备份失败；原数据未删除。' }
        } finally {
            # 即使备份失败，也尝试恢复原容器服务。
            Run-Docker 'Resume API after backup' ($ComposeArgs+@('start','api'))
        }
        Run-Docker 'Recreate services with persistent data' ($ComposeArgs+@('up','-d','--force-recreate','--wait','--wait-timeout','180'))
    } else {
        Run-Docker 'Start API, Web and nginx on localhost:8080' ($ComposeArgs+@('up','-d','--wait','--wait-timeout','180'))
    }
    Run-Docker 'Record container identity and status' ($ComposeArgs+@('ps','--format','json'))
    Run-Docker 'Verify Python environment inside Linux application container' ($ComposeArgs+@('exec','-T','api','python','-c',
        'import platform,torch,torchvision,clip,fastapi,sqlalchemy;print(platform.platform());print(torch.__version__,torch.version.cuda,torch.cuda.is_available());print(callable(clip.load))'))
    Run-Docker 'Check installed Python dependencies' ($ComposeArgs+@('exec','-T','api','python','-m','pip','check'))
    $env:GV_S3_API_URL='http://127.0.0.1:8080/api'
    if ($Maintenance) {
        & '.venv\Scripts\python.exe' scripts/verify_stage3_maintenance.py compare $MaintenanceRoot
        if ($LASTEXITCODE -ne 0) { throw '容器重建后的持久化验证失败，请反馈错误。' }
        $RestoreDir=(Join-Path $MaintenanceRoot 'restore-copy').Replace('\','/')
        Get-Content -LiteralPath 'scripts\verify_container_restore.py' -Raw -Encoding UTF8 | & $DockerExe @ComposeArgs run --rm -T --no-deps --volume "${RestoreDir}:/data" api python -
        if ($LASTEXITCODE -ne 0) { throw '隔离Linux容器中的备份恢复验证失败。' }
        $RestoreResult=Join-Path $MaintenanceRoot 'restore-copy\restore-result.json'
        if (!(Test-Path -LiteralPath $RestoreResult)) { throw '恢复容器未生成结果文件，验证未完成。' }
        $RestoreCheck=Get-Content -LiteralPath $RestoreResult -Raw -Encoding UTF8 | ConvertFrom-Json
        if (!$RestoreCheck.complete) { throw '恢复结果未通过，验证未完成。' }
        Copy-Item -LiteralPath $RestoreResult -Destination (Join-Path $EvidenceRoot 'restore-result.json')
        Copy-Item -LiteralPath (Join-Path $MaintenanceRoot 'persistence.json') -Destination (Join-Path $EvidenceRoot 'persistence.json')
    } else {
        & '.venv\Scripts\python.exe' -u scripts/verify_stage3_http.py data/raw/commons/commons-179028310.jpg data/raw/commons/commons-79273563.jpg --output $EvidenceRoot
        if ($LASTEXITCODE -ne 0) { throw 'Linux容器真实模型HTTP验证失败，请反馈错误。' }
    }
    $Report.complete=$true
    if ($Maintenance) { Write-Host '构建、容器重建、历史保留与Linux备份恢复验证通过。网页：http://127.0.0.1:8080' }
    else { Write-Host 'Linux容器构建、启动与两张真实图片推理验证通过。网页：http://127.0.0.1:8080' }
} catch {
    $ExitCode = 1
    $Report.error=$_.Exception.Message
    Write-Host $Report.error
} finally {
    foreach ($ProxyName in $ProxyBefore.Keys) {
        [Environment]::SetEnvironmentVariable($ProxyName,$ProxyBefore[$ProxyName],'Process')
    }
    $Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    Write-Host "进度记录：$ReportPath"
}
exit $ExitCode
