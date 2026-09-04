#!/usr/bin/env bash
set -euo pipefail
python3 -m pip install --user -e "$(cd "$(dirname "$0")/.." && pwd)"
