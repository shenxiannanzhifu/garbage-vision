param()
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
$ProjectRoot=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$DockerExe=Join-Path (Split-Path -Parent $ProjectRoot) 'runtime\docker-app\resources\bin\docker.exe'
if (!(Test-Path -LiteralPath $DockerExe)) { $DockerExe='docker' }
$RunId=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$EvidenceRoot=Join-Path $ProjectRoot 'evidence\stage3\linux-container'
$RunRoot=Join-Path $ProjectRoot ('.local\rollback\'+$RunId)
$ReportPath=Join-Path $EvidenceRoot ('rollback-'+$RunId+'.json')
$LogPath=Join-Path $EvidenceRoot ('rollback-'+$RunId+'.log')
$Report=[ordered]@{started_at=(Get-Date).ToUniversalTime().ToString('o');complete=$false;scope='isolated local Linux version switch';checks=@();phases=@();inference_requests_sent=0;original_service_modified=$false}
$ProjectName='gv-rollback-'+$RunId
$Started=$false
$ExitCode=0
$ApiUrlBefore=$env:GV_S3_API_URL

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
    if ($Code -ne 0) { throw "$Name 失败，请反馈末尾错误。" }
}

try {
    $Previous=Get-ChildItem -LiteralPath $EvidenceRoot -Filter 'maintenance-*.json' |
        Sort-Object LastWriteTime -Descending | ForEach-Object {
            $Candidate=Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($Candidate.complete -and $Candidate.rollback_image) { $Candidate }
        } | Select-Object -First 1
    if (!$Previous) { throw '没有已通过的维护备份，请先完成 -Maintenance。' }
    $Backup=Join-Path $Previous.maintenance_dir 'backup'
    if (!(Test-Path -LiteralPath (Join-Path $Backup 'tasks.sqlite3'))) { throw '维护备份不存在，未启动测试。' }
    # 已停服生成的不可变备份；不复制正在写入的在线数据库。
    New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
    Copy-Item -LiteralPath $Backup -Destination (Join-Path $RunRoot 'data') -Recurse
    Copy-Item -LiteralPath (Join-Path $Previous.maintenance_dir 'before.json') -Destination (Join-Path $RunRoot 'before.json')
    $NewTag='garbage-vision-stage3:rollback-test-current-'+$RunId
    Run-Docker 'Preserve current application image' @('tag','garbage-vision-stage3:local',$NewTag)
    $OldTag=[string]$Previous.rollback_image
    $Report.old_image=$OldTag; $Report.new_image=$NewTag
    $Report.backup_source=$Previous.maintenance_dir
    $DataPath=(Join-Path $RunRoot 'data').Replace('\','/')
    $OverridePath=Join-Path $RunRoot 'compose.rollback.yaml'
    $ComposeArgs=@('compose','--project-directory',$ProjectRoot,'-p',$ProjectName,'-f',(Join-Path $ProjectRoot 'compose.yaml'),'-f',$OverridePath)
    $env:GV_S3_API_URL='http://127.0.0.1:8081/api'
    foreach ($Phase in @(@{name='current';image=$NewTag},@{name='rollback';image=$OldTag},@{name='return-current';image=$NewTag})) {
        # !override要求Compose 2.24.4+；本机已验证5.6.0。仅测试项目改用8081。
        $Content=@"
services:
  api:
    image: $($Phase.image)
    environment:
      GV_S3_PAID_CALL_LIMIT: '0'
      GV_S3_AUTHORIZATION_ID: ''
    volumes:
      - type: bind
        source: '$DataPath'
        target: /data
    restart: 'no'
  web:
    image: $($Phase.image)
    restart: 'no'
  nginx:
    ports: !override
      - '127.0.0.1:8081:80'
    restart: 'no'
"@
        [IO.File]::WriteAllText($OverridePath,$Content,(New-Object System.Text.UTF8Encoding($false)))
        Run-Docker ('Validate '+$Phase.name) ($ComposeArgs+@('config','--quiet'))
        $Started=$true
        Run-Docker ('Switch isolated services to '+$Phase.name) ($ComposeArgs+@('up','-d','--no-build','--pull','never','--force-recreate','--wait','--wait-timeout','180'))
        # 检查两个应用容器实际使用的镜像ID，不只相信镜像标签。
        $ExpectedId=& $DockerExe image inspect $Phase.image --format '{{.Id}}'
        if ($LASTEXITCODE -ne 0) { throw '无法取得预期镜像ID。' }
        foreach ($ServiceName in @('api','web')) {
            $ContainerId=& $DockerExe @ComposeArgs ps -q $ServiceName
            if ($LASTEXITCODE -ne 0 -or !$ContainerId) { throw '测试容器未运行。' }
            $ActualId=& $DockerExe inspect $ContainerId --format '{{.Image}}'
            if ($LASTEXITCODE -ne 0 -or $ActualId -ne $ExpectedId) { throw '测试服务镜像ID与切换目标不一致。' }
        }
        & '.venv\Scripts\python.exe' scripts/verify_stage3_maintenance.py compare $RunRoot
        if ($LASTEXITCODE -ne 0) { throw '版本切换后历史、结果或图片校验失败。' }
        Copy-Item -LiteralPath (Join-Path $RunRoot 'persistence.json') -Destination (Join-Path $RunRoot ($Phase.name+'-persistence.json'))
        $Report.phases += [ordered]@{name=$Phase.name;image=$Phase.image;image_id=[string]$ExpectedId;api_and_web_image_match=$true;history_results_images_match=$true}
    }
    $Report.complete=$true
} catch {
    $ExitCode=1; $Report.error=$_.Exception.Message; Write-Host $Report.error
} finally {
    if ($Started) {
        try { Run-Docker 'Remove only isolated test containers and network' ($ComposeArgs+@('down')) }
        catch { $ExitCode=1; $Report.complete=$false; $Report.cleanup_error=$_.Exception.Message }
    }
    $env:GV_S3_API_URL=$ApiUrlBefore
    $Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    Write-Host "进度记录：$ReportPath"
}
if ($ExitCode -eq 0) { Write-Host '新版本 → 旧版本回滚 → 新版本恢复全部通过；8080原服务和任务未改动。' }
exit $ExitCode
