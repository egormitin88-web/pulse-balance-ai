param(
    [string]$PythonExe = '',
    [int]$Port = 8001
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $projectRoot 'backend'
$venvPython = Join-Path $backendRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not $PythonExe) {
        $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        if (Test-Path -LiteralPath $bundledPython) {
            $PythonExe = $bundledPython
        } else {
            $PythonExe = 'python'
        }
    }
    & $PythonExe -m venv (Join-Path $backendRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create a Python environment. Pass -PythonExe with a Python 3.11+ path.' }
}

& $venvPython -c 'import fastapi, uvicorn, sqlalchemy, pydantic, argon2, itsdangerous, openai, keyring, psycopg, dotenv, websockets' *> $null
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install -r (Join-Path $backendRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install Python dependencies.' }
}

Push-Location $backendRoot
try {
    Write-Host "Open http://127.0.0.1:$Port in your browser. Press Ctrl+C to stop."
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
