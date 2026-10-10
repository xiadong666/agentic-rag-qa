# ============================================================
# RAG knowledge-base QA system - Windows bootstrap script
# 1) create venv   2) install torch (CPU)   3) install requirements
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$proj = Split-Path -Parent $PSScriptRoot   # rag-qa-system/
$venvPy = Join-Path $proj ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPy)) {
    Write-Host "==> creating venv (.venv)"
    python -m venv (Join-Path $proj ".venv")
    if (-not (Test-Path $venvPy)) { throw "venv creation failed - is python 3.10~3.12 on PATH?" }
}

Write-Host "==> installing torch (CPU only)"
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install torch --index-url https://download.pytorch.org/whl/cpu

Write-Host "==> installing requirements"
& $venvPy -m pip install -r (Join-Path $proj "requirements.txt")

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  1) copy .env.example to .env and fill LLM_API_KEY"
Write-Host "  2) .\.venv\Scripts\python scripts\seed_demo.py   (optional demo data)"
Write-Host "  3) .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000"
