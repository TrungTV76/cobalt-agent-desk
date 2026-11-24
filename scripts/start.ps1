param(
    [string]$Repo = "",
    [int]$Port = 18780,
    [switch]$Demo,
    [switch]$NoBrowser,
    [switch]$Background,
    [switch]$Stop,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch {
    # Safe when launched without an interactive console handle
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ServerPy = Join-Path $RepoRoot "server.py"
$OutLog = Join-Path $RepoRoot "cobalt_desk.log"
$ErrLog = Join-Path $RepoRoot "cobalt_desk.err.log"
$PidFile = Join-Path $RepoRoot "cobalt_desk.pid"
$Url = "http://127.0.0.1:$Port"

function Resolve-PythonExe {
    foreach ($Candidate in @("python", "py", "python3")) {
        $Cmds = Get-Command $Candidate -All -ErrorAction SilentlyContinue
        foreach ($C in $Cmds) {
            if ($C.Source -and ($C.Source -notmatch "WindowsApps[\\/]python")) {
                return $C.Source
            }
        }
    }
    throw "Python 3.10+ was not found in PATH."
}

function Test-DeskHealth {
    param([string]$CheckUrl)
    try {
        $Resp = Invoke-RestMethod -Uri "$CheckUrl/api/health" -TimeoutSec 1 -ErrorAction Stop
        return (($Resp.ok -eq $true) -and ($Resp.app -eq "cobalt-agent-desk"))
    } catch {
        return $false
    }
}

function Stop-DeskInstance {
    param([int]$TargetPort)
    $Stopped = 0
    if (Test-Path $PidFile) {
        $SavedPid = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
        if ($SavedPid -match "^\d+$") {
            Stop-Process -Id ([int]$SavedPid) -Force -ErrorAction SilentlyContinue
            $Stopped++
        }
        Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
    }
    $Procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue
    foreach ($P in $Procs) {
        $Cmd = [string]$P.CommandLine
        $MatchesApp = ($Cmd -match "cobalt[-_]agent[-_]desk") -or ($Cmd -match "cobalt_desk")
        $MatchesPort = ($Cmd -match "--port\s+$TargetPort\b") -or (($TargetPort -eq 18780) -and ($Cmd -notmatch "--port\s+\d+"))
        if ($Cmd -and $MatchesApp -and $MatchesPort) {
            Stop-Process -Id $P.ProcessId -Force -ErrorAction SilentlyContinue
            $Stopped++
        }
    }
    return $Stopped
}

if ($Stop) {
    $Cnt = Stop-DeskInstance -TargetPort $Port
    Write-Host "[Cobalt Agent Desk] Stopped $Cnt running instance(s) on port $Port." -ForegroundColor Yellow
    exit 0
}

if ($Restart) {
    $Cnt = Stop-DeskInstance -TargetPort $Port
    if ($Cnt -gt 0) {
        Start-Sleep -Milliseconds 350
        Write-Host "[Cobalt Agent Desk] Stopped previous instance ($Cnt) for clean reload." -ForegroundColor Cyan
    }
}

if (Test-DeskHealth -CheckUrl $Url) {
    Write-Host "[Cobalt Agent Desk] Already running at $Url (use -Restart to reload)." -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $Url
    }
    exit 0
}

$PythonExe = Resolve-PythonExe
$ArgList = @($ServerPy, "--port", "$Port")
if ($Demo) { $ArgList += "--demo" }
if ($Repo) { $ArgList += @("--repo", $Repo) }

if ($Background) {
    Remove-Item -Path $OutLog, $ErrLog -Force -ErrorAction SilentlyContinue
    $QuotedArgs = $ArgList | ForEach-Object {
        if ($_ -match "\s") { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }
    $Proc = Start-Process -FilePath $PythonExe `
        -ArgumentList ($QuotedArgs -join " ") `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden -PassThru

    $ActualUrl = $Url
    $Ready = $false
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Milliseconds 200
        if ($Proc.HasExited) { break }
        if (Test-Path $OutLog) {
            $Line = Get-Content -Path $OutLog -Raw -ErrorAction SilentlyContinue
            if ($Line -match "(http://127\.0\.0\.1:\d+)") {
                $ActualUrl = $Matches[1]
            }
        }
        if (Test-DeskHealth -CheckUrl $ActualUrl) {
            $Ready = $true
            break
        }
    }

    if (-not $Ready) {
        Write-Host "[Cobalt Agent Desk] ERROR: Server failed to start on $ActualUrl." -ForegroundColor Red
        if (Test-Path $ErrLog) {
            Get-Content -Path $ErrLog -ErrorAction SilentlyContinue | Write-Host -ForegroundColor Red
        }
        exit 1
    }

    Set-Content -Path $PidFile -Value "$($Proc.Id)" -Encoding ASCII -ErrorAction SilentlyContinue
    Write-Host "[Cobalt Agent Desk] Started in background (PID=$($Proc.Id)) -> $ActualUrl" -ForegroundColor Green
    if (-not $NoBrowser) {
        Start-Process $ActualUrl
    }
    exit 0
}

if (-not $NoBrowser) {
    $ArgList += "--open-browser"
}

Write-Host "[Cobalt Agent Desk] Starting (Ctrl+C to stop)..." -ForegroundColor Cyan
& $PythonExe @ArgList
