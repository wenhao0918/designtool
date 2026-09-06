#!/usr/bin/env python3
"""DraftEngine CLI:模型文件 → 工程图纸 SVG。

用法:
    python -m draftengine.cli part.step -o out.svg
    python -m draftengine.cli part.step --json meta.json
    python -m draftengine.cli part.step -t "底板" -p "项目A" --out-dir /tmp
"""

import argparse
import json
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="draftengine", description="3D 模型 → 工程图纸(工程画图)")
    ap.add_argument("model", help="输入模型文件(.step/.stp/.iges/.igs/.brep)")
    ap.add_argument("-o", "--output", help="输出 SVG 路径(默认: <模型名>_drawing.svg)")
    ap.add_argument("--json", dest="json_out", help="输出结构化 meta 到 JSON 文件")
    ap.add_argument("-t", "--title", default="", help="图纸标题")
    ap.add_argument("-p", "--project", default="", help="项目名")
    ap.add_argument("--out-dir", default=".", help="输出目录(未指定 -o 时使用)")
    ap.add_argument("--draft", action="store_true",
                    help="中间态:仅三视图(HLR),无标注/标题栏,不出 PDF/FCStd")
    args = ap.parse_args(argv)

    from . import generate_drawing

    out_dir = os.path.dirname(args.output) if args.output else args.out_dir
    r = generate_drawing(args.model, out_dir, title=args.title, project=args.project,
                         filename=os.path.basename(args.model), draft=args.draft)
    if "error" in r:
        print("错误:", r["error"], file=sys.stderr)
        return 1
    if args.output:
        os.replace(r["svg"], args.output)
        print("图纸:", args.output)
    else:
        print("图纸:", r["svg"])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(r["meta"], f, ensure_ascii=False, indent=2)
        print("meta:", args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
