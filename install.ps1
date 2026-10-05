# Ruttla installieren (Windows): eigene Python-Umgebung, dann Paket und
# passende Rust-Engine aus dem letzten GitHub-Release (`ruttla update`).
#
#   irm https://raw.githubusercontent.com/hehljo/Ruttla/main/install.ps1 | iex
#
# Erneut ausfuehren oder `ruttla update` holt den neuesten Stand.
# Einstellbar: RUTTLA_HOME (Vorgabe %LOCALAPPDATA%\ruttla),
# RUTTLA_CHANNEL (auto|stable|nightly).
# Bewusst nur ASCII: Windows PowerShell 5.1 liest Dateien ohne BOM als ANSI.

$ErrorActionPreference = 'Stop'

$RuttlaHome = if ($env:RUTTLA_HOME) { $env:RUTTLA_HOME } else { Join-Path $env:LOCALAPPDATA 'ruttla' }
$Channel = if ($env:RUTTLA_CHANNEL) { $env:RUTTLA_CHANNEL } else { 'auto' }
$Bootstrap = 'ruttla @ https://github.com/hehljo/Ruttla/archive/refs/heads/main.tar.gz'

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "ruttla-install: '$Exe $($Arguments -join ' ')' endete mit Exit $LASTEXITCODE." }
}

# Python >= 3.11: zuerst der Launcher `py -3`, dann `python`.
$Python = $null
foreach ($cand in @(@('py', '-3'), @('python'))) {
    if (-not (Get-Command $cand[0] -ErrorAction SilentlyContinue)) { continue }
    $candArgs = @($cand | Select-Object -Skip 1)
    & $cand[0] @candArgs -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>$null
    if ($LASTEXITCODE -eq 0) { $Python = $cand; break }
}
if (-not $Python) { throw 'ruttla-install: Python >= 3.11 nicht gefunden (https://www.python.org/downloads/ oder winget install Python.Python.3.13).' }
$PyArgs = @($Python | Select-Object -Skip 1)

$Venv = Join-Path $RuttlaHome 'venv'
Invoke-Checked $Python[0] ($PyArgs + @('-m', 'venv', $Venv))
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Ruttla = Join-Path $Venv 'Scripts\ruttla.exe'
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip')
Invoke-Checked $VenvPython @('-m', 'pip', 'install', '--quiet', $Bootstrap)
Invoke-Checked $Ruttla @('update', '--channel', $Channel)

$Scripts = Join-Path $Venv 'Scripts'
$UserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (($UserPath -split ';') -contains $Scripts)) {
    $NewPath = if ($UserPath) { "$UserPath;$Scripts" } else { $Scripts }
    [Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
    Write-Host "Hinweis: $Scripts wurde zum Benutzer-PATH hinzugefuegt - neues Terminal oeffnen."
}
$env:Path = "$Scripts;$env:Path"
Write-Host "Ruttla installiert: $Ruttla ($(& $Ruttla --version))"
