param(
    [string]$RemoteUrl = $env:AGENT_BRIDGE_REMOTE,
    [string]$PackageSource,
    [switch]$Yes,
    [switch]$SkipCodex,
    [switch]$SkipLogin
)

$ErrorActionPreference = 'Stop'
$Repo = 'Nagumo-Ryunosuke/github-agent-bridge'
$Ref = if ($env:AGENT_BRIDGE_REF) { $env:AGENT_BRIDGE_REF } else { 'main' }
$ArchiveUrl = "https://github.com/$Repo/archive/refs/heads/$Ref.zip"
if ($PackageSource) { $ArchiveUrl = $PackageSource }
$StateRoot = Join-Path $env:LOCALAPPDATA 'github-agent-bridge'
$Venv = Join-Path $StateRoot 'venv'
$BinDir = Join-Path $StateRoot 'bin'
$BridgeCmd = Join-Path $BinDir 'agent-bridge.cmd'

function Write-Step([string]$Text) {
    Write-Host "`n==> $Text"
}

function Get-PythonPath {
    $candidates = @()
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) { $candidates += $python.Source }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $resolved = & $py.Source -3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) { $candidates += $resolved.Trim() }
        } catch {}
    }
    $programs = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $programs) {
        $candidates += Get-ChildItem $programs -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName 'python.exe' }
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path $candidate)) { continue }
        try {
            & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)"
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }
    return $null
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user;$BinDir;$env:USERPROFILE\.local\bin"
}

if (-not $Yes) {
    Write-Host @'
github-agent-bridge will now prepare this Windows user account.

It may:
  * install Python when it is missing;
  * create/update a private user virtual environment;
  * install missing Git, GitHub CLI and Codex CLI using WinGet/official installers;
  * install the shared Skill under ~/.agents/skills/github-agent-bridge;
  * start GitHub and ChatGPT/Codex login flows.

GitHub and Codex authentication remain interactive and are never bypassed or stored
by github-agent-bridge.
'@
    $answer = Read-Host 'Proceed? [y/N]'
    if ($answer -notmatch '^(?i:y|yes)$') {
        Write-Host 'No changes made.'
        exit 2
    }
}

$pythonPath = Get-PythonPath
if (-not $pythonPath) {
    Write-Step 'Installing Python 3 with WinGet'
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python >=3.9 is missing and WinGet is unavailable. Install Microsoft App Installer/WinGet, then rerun this script.'
    }
    & $winget.Source install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements --silent
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed with exit code $LASTEXITCODE" }
    Refresh-ProcessPath
    $pythonPath = Get-PythonPath
    if (-not $pythonPath) {
        throw 'Python was installed but could not be resolved in the current process. Open a new PowerShell window and rerun the same bootstrap command.'
    }
}

Write-Step "Installing github-agent-bridge into $Venv"
New-Item -ItemType Directory -Force -Path $StateRoot, $BinDir | Out-Null
$venvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    & $pythonPath -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python virtual environment.' }
}
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Failed to upgrade pip.' }
& $venvPython -m pip install --upgrade $ArchiveUrl
if ($LASTEXITCODE -ne 0) { throw 'Failed to install github-agent-bridge.' }

$venvBridge = Join-Path $Venv 'Scripts\agent-bridge.exe'
if (-not (Test-Path $venvBridge)) { throw "agent-bridge executable was not created at $venvBridge" }

$cmdContent = "@echo off`r`nchcp 65001 >nul`r`nset PYTHONUTF8=1`r`n`"$venvBridge`" %*`r`n"
[IO.File]::WriteAllText($BridgeCmd, $cmdContent, [Text.UTF8Encoding]::new($false))

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$parts = @($userPath -split ';' | Where-Object { $_ })
if ($parts -notcontains $BinDir) {
    $newUserPath = (($parts + $BinDir) -join ';')
    [Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
}
Refresh-ProcessPath

Write-Step 'Installing the shared Codex Skill'
& $venvBridge skill install --scope user
if ($LASTEXITCODE -ne 0) { throw 'Skill installation failed.' }

$bridgeArgs = @('env', 'install', '--yes')
if ($SkipCodex) { $bridgeArgs += '--skip-codex' }
if ($SkipLogin) { $bridgeArgs += '--skip-login' }

Write-Step 'Installing/checking external prerequisites'
& $venvBridge @bridgeArgs
if ($LASTEXITCODE -ne 0) {
    throw 'External prerequisite setup did not complete. Rerun `agent-bridge env install` after fixing the reported item.'
}

if ($RemoteUrl) {
    Write-Step 'Preparing the target repository'
    $connectArgs = @('connect', $RemoteUrl, '--yes', '--skip-install', '--skip-login')
    & $venvBridge @connectArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Repository setup needs authorization. After login, resume with: agent-bridge connect $RemoteUrl"
    }
}

Write-Host @"

Installation complete.

Skill:       $env:USERPROFILE\.agents\skills\github-agent-bridge
CLI:         $BridgeCmd
Environment: $Venv

Open or restart Codex App/CLI so it reloads the Skill. Then open a target Git repository
and ask Codex to use `$github-agent-bridge. On first use it will run readiness checks,
ask only for unresolved permission/authentication steps, and continue setup.
"@
