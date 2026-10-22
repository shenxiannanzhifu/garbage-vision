# Local-only preparation. Never creates a cloud resource or calls a paid model.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$Docker = Join-Path (Split-Path -Parent $Root) 'runtime/docker-app/resources/bin/docker.exe'
$Python = Join-Path $Root '.venv/Scripts/python.exe'
$RunId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$Out = Join-Path $Root ('.local/remote-prep/'+$RunId)
New-Item -ItemType Directory -Path $Out -Force | Out-Null
$Report = [ordered]@{complete=$false;scope='local GPU preflight only';remote_verified=$false;paid_calls=0;checks=@()}
$Container = 'gv-gpu-preflight-'+$RunId
$Created = $false
$Before = @{}
foreach($Name in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','GV_S3_API_URL')) {
    $Before[$Name]=[Environment]::GetEnvironmentVariable($Name,'Process')
}
function Run-Docker([string]$Name,[string[]]$Arguments) {
    Write-Host ('执行：'+$Name)
    $OldPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    & $Docker @Arguments 2>&1 | ForEach-Object {
        $Line=$_.ToString(); Write-Host $Line
        Add-Content -LiteralPath (Join-Path $Out 'prepare.log') -Value $Line -Encoding UTF8
    }
    $Code=$LASTEXITCODE
    $ErrorActionPreference=$OldPreference
    $Report.checks += [ordered]@{name=$Name;exit_code=$Code}
    if($Code -ne 0){throw ($Name+' failed; see prepare.log')}
}
$ExitCode=0
try {
    $Status=& git status --porcelain
    if($LASTEXITCODE -ne 0 -or $Status){throw 'Commit the stage3 source before building the versioned deployment image.'}
    $Commit=(& git rev-parse HEAD).Trim()
    if($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$'){throw 'Cannot resolve source commit.'}
    $Image='garbage-vision-stage3:gpu-'+$Commit.Substring(0,12)
    $Report.commit=$Commit; $Report.image=$Image
    & $Python scripts/prepare_remote_assets.py --check
    if($LASTEXITCODE -ne 0){throw 'Model/sample checks failed.'}
    if(!(Test-Path -LiteralPath '.env.stage3')){throw 'Missing local service configuration.'}
    $Disk=New-Object System.IO.DriveInfo([System.IO.Path]::GetPathRoot($Out))
    if($Disk.AvailableFreeSpace -lt 40GB){throw 'At least 40 GiB free space is required for build and export.'}
    $ProxyUrl=''
    $WindowsProxy=Get-ItemProperty -LiteralPath 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Internet Settings' -ErrorAction SilentlyContinue
    if($WindowsProxy.ProxyEnable -eq 1 -and $WindowsProxy.ProxyServer){
        $Server=[string]$WindowsProxy.ProxyServer
        if($Server -match '(?:^|;)http=([^;]+)'){$Server=$Matches[1]}
        elseif($Server.Contains(';') -or $Server.Contains('=')){throw 'Unsupported proxy format.'}
        $ProxyUrl=if($Server -match '^https?://'){$Server}else{'http://'+$Server}
        $Uri=[uri]$ProxyUrl
        if(!$Uri.Host -or $Uri.UserInfo -or $Uri.Scheme -notin @('http','https')){throw 'Invalid proxy address.'}
        foreach($Name in @('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')){[Environment]::SetEnvironmentVariable($Name,$ProxyUrl,'Process')}
        $env:NO_PROXY='localhost,127.0.0.1,::1,host.docker.internal'
        Write-Host ('本次构建使用已有代理：'+$Uri.Host+':'+$Uri.Port)
    }
    $Build=@('build','--platform','linux/amd64','--progress','plain','--tag',$Image,'--label',('org.opencontainers.image.revision='+$Commit),'--build-arg','TORCH_INDEX=https://download.pytorch.org/whl/cu128')
    if($ProxyUrl){
        $EngineProxy=& $Docker info --format '{{.HTTPProxy}}'
        if($LASTEXITCODE -ne 0 -or !$EngineProxy){throw 'Docker internal proxy is unavailable.'}
        $EngineProxy=([string]$EngineProxy).Trim()
        if($EngineProxy -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://'){$EngineProxy='http://'+$EngineProxy}
        $EngineUri=[uri]$EngineProxy
        if(!$EngineUri.Host -or $EngineUri.UserInfo -or $EngineUri.Scheme -notin @('http','https')){throw 'Invalid internal proxy format.'}
        foreach($Name in @('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy')){$Build+=@('--build-arg',($Name+'='+$EngineProxy))}
    }
    Run-Docker 'Build independent CUDA image' ($Build+@('.'))
    Run-Docker 'Check dependencies' @('run','--rm',$Image,'python','-m','pip','check')
    Run-Docker 'Check CUDA execution' @('run','--rm','--gpus','all',$Image,'python','-c','import torch;assert torch.cuda.is_available();x=torch.ones(4,device=torch.device(0));assert x.sum().item()==4;print(torch.cuda.get_device_name())')
    $Data=Join-Path $Out 'data'; New-Item -ItemType Directory -Path $Data | Out-Null
    $WeightMount='type=bind,source='+$Root.Replace('\','/')+'/weights,target=/app/weights,readonly'
    $DataMount='type=bind,source='+$Data.Replace('\','/')+',target=/data'
    Run-Docker 'Start isolated GPU API on 8082' @('run','-d','--name',$Container,'--label','gv.scope=local-gpu-preflight','--gpus','all','--publish','127.0.0.1:8082:8000','--env-file',(Join-Path $Root '.env.stage3'),'--env','GV_S3_DEVICE=cuda:0','--env','GV_S3_DATA_DIR=/data','--env','GV_S3_PAID_CALL_LIMIT=0','--mount',$WeightMount,'--mount',$DataMount,$Image)
    $Created=$true
    $Ready=$false
    for($Attempt=0;$Attempt -lt 60;$Attempt++){
        try {$Response=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8082/health/live' -TimeoutSec 2; if($Response.StatusCode -eq 200){$Ready=$true;break}} catch {}
        Start-Sleep -Seconds 2
    }
    if(!$Ready){throw 'GPU API did not become healthy.'}
    $env:GV_S3_API_URL='http://127.0.0.1:8082'
    & $Python -u scripts/verify_stage3_http.py data/raw/commons/commons-179028310.jpg data/raw/commons/commons-79273563.jpg --output $Out
    if($LASTEXITCODE -ne 0){throw 'Real GPU image checks failed.'}
    $Summary=Get-Content -LiteralPath (Join-Path $Out 'summary.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if($Summary.tasks.Count -ne 2 -or @($Summary.tasks | Where-Object {$_.device -ne 'cuda:0' -or $_.status -ne 'succeeded'}).Count -gt 0){throw 'Expected two succeeded CUDA tasks.'}
    Run-Docker 'Validate Linux bootstrap syntax' @('run','--rm','--mount',('type=bind,source='+$Root.Replace('\','/')+'/scripts,target=/checks,readonly'),$Image,'bash','-n','/checks/deploy_prebuilt.sh')
    Run-Docker 'Ensure nginx image is available' @('pull','nginx:1.28-alpine')
    $FinalStatus=& git status --porcelain
    if($LASTEXITCODE -ne 0 -or $FinalStatus -or ((& git rev-parse HEAD).Trim() -ne $Commit)){throw 'Source changed during preparation; do not package a mismatched image.'}
    $ImageId=& $Docker image inspect --format '{{.Id}}' $Image
    if($LASTEXITCODE -ne 0 -or $ImageId -notmatch '^sha256:[0-9a-f]{64}$'){throw 'Cannot verify built image identity.'}
    $Report.image_id=$ImageId
    @{image_id=$ImageId} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Out 'image-identity.json') -Encoding UTF8
    Run-Docker 'Export app and nginx images' @('image','save','--output',(Join-Path $Out 'images.tar'),$Image,'nginx:1.28-alpine')
    & $Python scripts/prepare_remote_assets.py --out $Out --commit $Commit --image $Image
    if($LASTEXITCODE -ne 0){throw 'Deployment bundle export failed.'}
    $Report.complete=$true
    Write-Host '本机GPU两图预检与部署包准备通过。尚未购买或验证远端服务器。'
} catch {
    $ExitCode=1; $Report.error=$_.Exception.Message; Write-Host $Report.error
} finally {
    if($Created){
        try { Run-Docker 'Remove this isolated preflight container' @('rm','-f',$Container) }
        catch { $ExitCode=1; $Report.complete=$false; $Report.cleanup_error=$_.Exception.Message; Write-Host 'Cleanup failed; the named preflight container needs inspection.' }
    }
    foreach($Name in $Before.Keys){[Environment]::SetEnvironmentVariable($Name,$Before[$Name],'Process')}
    $Report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $Out 'prepare-result.json') -Encoding UTF8
    Write-Host ('进度记录：'+(Join-Path $Out 'prepare-result.json'))
}
exit $ExitCode
