# Arranca trading-replay en http://127.0.0.1:8000 (Windows / PowerShell)
# Uso: clic derecho > "Ejecutar con PowerShell", o desde una terminal: .\iniciar.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "No se encuentra 'uv'. Instálalo desde https://docs.astral.sh/uv/ y vuelve a intentarlo."
    exit 1
}

uv sync --quiet
uv run uvicorn trading_replay.app:app --host 127.0.0.1 --port 8000 @args
