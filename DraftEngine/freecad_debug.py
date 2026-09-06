# -*- coding: utf-8 -*-
"""Run a Python file inside FreeCAD and wait for VS Code debugpy attach."""
import runpy
import os

import debugpy

target = os.environ.get("FREECAD_DEBUG_TARGET")
if not target:
    raise SystemExit("FREECAD_DEBUG_TARGET is not set")

debugpy.listen(("127.0.0.1", 5678))
print("FREECAD_DEBUG_READY", flush=True)
debugpy.wait_for_client()
os.sys.argv = [target]
runpy.run_path(target, run_name="__main__")
