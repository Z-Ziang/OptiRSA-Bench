$ErrorActionPreference = 'Stop'
$packageDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $packageDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & py -3.12 -m venv (Join-Path $packageDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
}
& $pythonExe -m pip install -r (Join-Path $PSScriptRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $pythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
