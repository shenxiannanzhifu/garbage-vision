param(
    [Parameter(Mandatory=$true)][string]$ServerAddress,
    [ValidateSet('Inspect','Upload','Deploy','Tunnel','Status','Restart')][string]$Action = 'Inspect',
    [string]$Bundle = '',
    [switch]$FirstConnection
)
# Windows OpenSSH only. Keep all private material in the project's ignored .local.
# FirstConnection prompts for the server host key; compare it with the ECS console.
$ErrorActionPreference = 'Stop'
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($ServerAddress, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    $parsedAddress.ToString() -ne $ServerAddress) { throw 'Use the exact public IPv4 from the ECS console.' }
$root = Split-Path $PSScriptRoot -Parent
$sshDir = Join-Path $root '.local\ssh'
$key = Join-Path $sshDir 'gv-stage3-20261022.pem'
$sessionDir = Join-Path $root '.local\remote-session'
[IO.Directory]::CreateDirectory($sessionDir) | Out-Null
$known = Join-Path $sessionDir 'known_hosts'
if (-not (Test-Path -LiteralPath $key -PathType Leaf)) { throw 'The saved private key is missing.' }
$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$sftp = Join-Path $env:WINDIR 'System32\OpenSSH\sftp.exe'
$dest = 'ecs-user@' + $ServerAddress
$strict = 'yes'
if ($FirstConnection) {
    if ($Action -ne 'Inspect') { throw 'FirstConnection is only allowed for Inspect.' }
    $strict = 'ask'
}
$opts = @('-i', $key, '-o', 'IdentitiesOnly=yes', '-o', ('UserKnownHostsFile=' + $known.Replace('\','/')),
    '-o', ('StrictHostKeyChecking=' + $strict), '-o', 'ConnectTimeout=20',
    '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=6')
if (-not $FirstConnection) { $opts += @('-o', 'BatchMode=yes') }
$remoteDir = 'gv-stage3-upload-20261022-145939-655'
function Assert-NativeExit([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE). Do not purchase another instance; inspect the error." }
}
switch ($Action) {
    'Inspect' {
        # No environment dumps: never print server credentials.
        $command = 'set -eu; uname -srmo; cat /etc/os-release; date -Is; df -h /; free -h; nvidia-smi; sudo -n docker version; sudo -n docker compose version; command -v nvidia-container-runtime; python3 --version'
        & $ssh @opts $dest $command
        Assert-NativeExit 'Server inspection'
    }
    'Upload' {
        if (-not $Bundle) { $Bundle = Join-Path $root '.local\remote-prep\20261022-145939-655\bundle' }
        $bundlePath = (Resolve-Path -LiteralPath $Bundle).Path
        if ($bundlePath -match '["\r\n]') { throw 'Unsupported bundle path.' }
        $manifest = Get-Content -LiteralPath (Join-Path $bundlePath 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $expected = @('deploy_prebuilt.sh','images.tar.gz','runtime-assets.tar.gz','source.tar.gz')
        $actual = @($manifest.files.PSObject.Properties.Name | Sort-Object)
        if (($actual -join ',') -ne (($expected | Sort-Object) -join ',')) { throw 'Unexpected bundle file list.' }
        Write-Host 'Verifying bundle hashes before transfer...'
        foreach ($name in $expected) {
            $file = Join-Path $bundlePath $name
            $record = $manifest.files.$name
            if ((Get-Item -LiteralPath $file).Length -ne $record.bytes -or
                (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.sha256) {
                throw "Bundle checksum mismatch: $name"
            }
        }
        # Windows OpenSSH reput requires an existing destination. Use put for
        # the first upload, then reput only for files already on this server.
        $existing = @(& $ssh @opts $dest ('mkdir -p ' + $remoteDir + '; cd ' + $remoteDir + '; for f in images.tar.gz runtime-assets.tar.gz source.tar.gz; do if test -f "$f"; then printf "%s\n" "$f"; fi; done'))
        Assert-NativeExit 'Remote upload inventory'
        # A final server checksum check is mandatory after any resumed transfer.
        $lines = @('lcd "' + $bundlePath.Replace('\','/') + '"')
        $lines += 'cd ' + $remoteDir
        foreach ($name in @('images.tar.gz','runtime-assets.tar.gz','source.tar.gz')) {
            $operation = if ($existing -contains $name) { 'reput ' } else { 'put ' }
            $lines += $operation + $name
        }
        $lines += @('put deploy_prebuilt.sh', 'put manifest.json')
        $batch = Join-Path $sessionDir 'upload.sftp'
        [IO.File]::WriteAllText($batch, (($lines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
        & $sftp @opts '-b' $batch $dest
        Assert-NativeExit 'Resumable upload'
        & $ssh @opts $dest ('cd ' + $remoteDir + '; sha256sum images.tar.gz runtime-assets.tar.gz source.tar.gz deploy_prebuilt.sh')
        Assert-NativeExit 'Remote checksum readout'
        Write-Host 'Upload finished. Deployment validates every remote SHA256 against the manifest again.'
    }
    'Deploy' {
        # pipefail preserves bootstrap failures; no .env or token is printed.
        $command = 'cd ' + $remoteDir + ' && set -o pipefail && sudo -n bash deploy_prebuilt.sh 2>&1 | tee deploy.log'
        & $ssh @opts $dest $command
        Assert-NativeExit 'Remote deployment'
    }
    'Tunnel' {
        Write-Host 'Remote webpage: http://127.0.0.1:18080/ . Keep this terminal open; Ctrl+C closes only the tunnel.'
        & $ssh @opts '-o' 'ExitOnForwardFailure=yes' '-N' '-L' '127.0.0.1:18080:127.0.0.1:8080' $dest
        Assert-NativeExit 'SSH tunnel'
    }
    { $_ -in @('Status','Restart') } {
        # The update script switches this pointer only after history/restore checks.
        $release = '/home/ecs-user/gv-stage3-active'
        $compose = 'sudo -n docker compose -f compose.yaml -f compose.gpu.yaml -f .local/prebuilt.json'
        # sudo bash is needed to enter the private release directory.
        $body = 'set -eu; cd ' + $release + '; '
        if ($Action -eq 'Restart') {
            $body += $compose + ' stop; ' + $compose + ' up -d --no-build --pull never --wait --wait-timeout 180; '
        }
        $body += $compose + ' ps; curl --fail --silent http://127.0.0.1:8080/api/health/live'
        & $ssh @opts $dest ('sudo -n bash -c ' + "'" + $body + "'")
        Assert-NativeExit ('Remote ' + $Action)
    }
}
