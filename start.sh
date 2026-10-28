#!/usr/bin/env bash
# WorldBranch 一键启动（Linux / macOS）
#
#   ./start.sh              默认 5210 端口
#   ./start.sh --port 8080  换端口
#
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "没找到 Python。请先安装 Python 3.10 或更高版本。"
  exit 1
fi

exec "$PY" tools/bootstrap.py "$@"