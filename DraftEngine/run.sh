#!/bin/bash
# DraftEngine 启动脚本:自动探测并设置 FreeCAD 库路径,然后拉起 API 服务
set -e
cd "$(dirname "$0")"

# FreeCAD 库路径(按 snap / apt 两种安装位置探测)
for cand in /snap/freecad/current/usr/lib/freecad/lib \
            /usr/lib/freecad/lib \
            /usr/lib/freecad-python3/lib; do
    if [ -d "$cand" ]; then
        export PYTHONPATH="$cand:$PYTHONPATH"
        export LD_LIBRARY_PATH="$cand:$LD_LIBRARY_PATH"
        break
    fi
done

PORT="${DRAFTENGINE_PORT:-8100}"
echo "DraftEngine starting on :${PORT}"
exec python3 -m draftengine.api
