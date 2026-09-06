#!/bin/bash
cd "$(dirname "$0")"
PYTHONPATH=/usr/lib/freecad-python3/lib:/mnt/data/develop/elderly-care-robot/DesignTool \
  python3 -m cadmcp.api --port 8102 >> /mnt/data/develop/elderly-care-robot/logs/cadservice.log 2>&1
