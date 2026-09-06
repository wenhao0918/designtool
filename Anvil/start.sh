#!/bin/bash
cd "$(dirname "$0")"
set -a
source .env
set +a
# 数据目录与源码分离:运行时数据(projects/output/anvil.db/日志)全在 data/
export ANVIL_DATA_DIR="${ANVIL_DATA_DIR:-$PWD/data}"
exec /usr/local/opt/python@3.11/bin/python3.11 -m uvicorn anvil.web:app --host 0.0.0.0 --port 8093
