#!/usr/bin/env bash
set -euo pipefail

backend_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$backend_dir/.venv/bin/python"

if [[ ! -x "$python_bin" ]]; then
  echo "No existe backend/.venv. Cree el entorno e instale requirements.txt." >&2
  exit 1
fi

cd "$backend_dir"
exec "$python_bin" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
