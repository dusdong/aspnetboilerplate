#!/bin/bash
set -euo pipefail

entry=$(cd "$(dirname "$0")" && pwd -P)
exec python3 -B "$entry/pack-r3-module-zero-candidates.py" "$@"
