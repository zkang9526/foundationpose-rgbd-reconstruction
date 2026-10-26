#!/usr/bin/env bash
set -euo pipefail
LOGGED_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -u "$LOGGED_SCRIPT_DIR/run_logged.py" "$@"
