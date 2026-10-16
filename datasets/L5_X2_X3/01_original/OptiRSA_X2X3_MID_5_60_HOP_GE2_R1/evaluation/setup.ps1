$ErrorActionPreference = 'Stop'
$packageDir = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $packageDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & py -3.12 -m venv (Join-Path $packageDir '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required.' }
}
& $pythonExe -m pip install --no-index --find-links (Join-Path $PSScriptRoot 'vendor\common') --find-links (Join-Path $PSScriptRoot 'vendor\windows_py312') -r (Join-Path $PSScriptRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Offline dependency installation failed; see README.' }
& $pythonExe -c "import inspect_ai, importlib.metadata as m; print('Inspect AI',m.version('inspect-ai'))"
