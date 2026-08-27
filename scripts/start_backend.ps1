$ErrorActionPreference = "Stop"
$BackendRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $BackendRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "No existe backend/.venv. Cree el entorno e instale requirements.txt."
}

Set-Location -LiteralPath $BackendRoot
& $Python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
