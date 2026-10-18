#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/00_common.sh"
verify_backend() {
    curl --fail --silent --show-error --max-time 10 "http://127.0.0.1:${BACKEND_PORT}/health/ready"
    echo
    curl --fail --silent --show-error --max-time 15 "http://127.0.0.1:${BACKEND_PORT}/health/ai"
    echo
}
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then verify_backend; fi
