#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for candidate in "$HERE/scripts/deploy/platform.sh" "$HERE/backend/scripts/deploy/platform.sh" "$HERE/DrapeMind-Backend/scripts/deploy/platform.sh"; do
    if [[ -f "$candidate" ]]; then exec bash "$candidate" "$@"; fi
done
printf 'Primero ejecuta python3 instalar_vps.py para preparar los repositorios.\n' >&2
exit 1
