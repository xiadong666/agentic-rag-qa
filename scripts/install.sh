# ============================================================
# RAG knowledge-base QA system - Linux/macOS bootstrap
# Usage: bash scripts/install.sh
# ============================================================
#!/usr/bin/env bash
set -euo pipefail
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$PROJ/.venv/bin/python"

if [ ! -f "$VENV_PY" ]; then
  echo "==> creating venv (.venv)"
  python3 -m venv "$PROJ/.venv"
fi

echo "==> installing torch (CPU only)"
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install torch --index-url https://download.pytorch.org/whl/cpu

echo "==> installing requirements"
"$VENV_PY" -m pip install -r "$PROJ/requirements.txt"

echo ""
echo "Done. Next:"
echo "  1) cp .env.example .env  # fill LLM_API_KEY"
echo "  2) $VENV_PY scripts/seed_demo.py"
echo "  3) $VENV_PY -m uvicorn app.main:app --reload --port 8000"
