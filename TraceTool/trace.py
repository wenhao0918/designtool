#!/usr/bin/env python3
"""
TraceTool — 知识溯源 CLI 工具
管理 Source → Refinery → Output 溯源链。

用法:
  trace source add -t "标题" [-c "内容" | -f 文件 | stdin]
  trace refinery add -t "标题" -s S-001,S-002 [-o output] [-c "内容" | -f 文件 | stdin]
  trace status
  trace list [sources|refineries]
  trace init [目录]

Output 版本管理（模仿 git）:
  trace log [file]              语义版本历史
  trace show <ref> [file]       查看某 Refinery 时的快照
  trace diff <from> <to> [file] 两个版本间 diff
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# Project Discovery
# ═══════════════════════════════════════════════════════════════

def find_project_root(start: Path | None = None) -> Path | None:
    """向上查找包含 .PROJECT.md + .sources/ 的目录。"""
    if start is None:
        start = Path.cwd()
    for p in [start] + list(start.parents):
        if (p / ".PROJECT.md").exists() and (p / ".sources").is_dir():
            return p
    return None


def require_project() -> Path:
    root = find_project_root()
    if not root:
        print("错误: 未找到溯源项目 (需要 .PROJECT.md + .sources/ 目录)", file=sys.stderr)
        print("提示: 用 'trace init' 初始化，或切到项目目录下", file=sys.stderr)
        sys.exit(1)
    return root


# ═══════════════════════════════════════════════════════════════
# Git helpers
# ═══════════════════════════════════════════════════════════════

def _git_root(project_root: Path) -> Path | None:
    """返回 git 仓库根目录，不在 git 中返回 None。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=project_root
        )
        if r.returncode == 0:
            return Path(r.stdout.strip())
    except FileNotFoundError:
        pass
    return None


def _git_has_changes(git_root: Path, *files: str) -> bool:
    """检查文件是否有未提交的变更（ staged 或 unstaged）。"""
    for f in files:
        # staged changes
        r = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", f],
            cwd=git_root
        )
        if r.returncode != 0:
            return True
        # unstaged changes
        r = subprocess.run(
            ["git", "diff", "--quiet", "--", f],
            cwd=git_root
        )
        if r.returncode != 0:
            return True
        # untracked
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", f],
            capture_output=True, cwd=git_root
        )
        if r.returncode != 0:
            return True
    return False


def _git_commit_refinery(project_root: Path, ref_id: str, title: str,
                         sources: str, output: str) -> str | None:
    """Refinery 触发的 git commit。返回 commit hash 或 None。
    
    commit 策略：
    - R-NNN.md（Refinery 记录）始终 stage——它本身就是变更
    - output 文件有变更则一起 stage
    - 即使 output 无变更，Refinery 记录本身也值得一次 commit（保证 git 历史可追溯）
    """
    git_root = _git_root(project_root)
    if not git_root:
        return None

    rel_ref = str((project_root / ".refineries" / f"{ref_id}.md").relative_to(git_root))

    # 去重：检查 refinery 文件是否已在 git 历史中
    existing = subprocess.run(
        ["git", "log", "--oneline", "--format=%H", "-1", "--", rel_ref],
        capture_output=True, text=True, cwd=git_root
    )
    if existing.stdout.strip():
        return existing.stdout.strip()

    # 收集要 stage 的文件
    files = []
    files.append(rel_ref)

    if output:
        for out in output.split(","):
            out = out.strip()
            if "#" in out:
                out = out.split("#")[0]
            out_path = project_root / out
            if out_path.exists():
                try:
                    files.append(str(out_path.relative_to(git_root)))
                except ValueError:
                    pass

    # 至少 refinery 文件本身是新创建的，一定会有变更
    # 强制 stage 并 commit
    for f in files:
        subprocess.run(
            ["git", "add", "--", f],
            capture_output=True, text=True, cwd=git_root
        )

    msg = f"{ref_id}: {title}\n\nref: {ref_id}\nsources: {sources}"
    r = subprocess.run(
        ["git", "commit", "-m", msg],
        capture_output=True, text=True, cwd=git_root
    )
    if r.returncode == 0:
        hr = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=git_root
        )
        if hr.returncode == 0:
            return hr.stdout.strip()[:7]
    return None


def _commit_for_ref(git_root: Path, ref: str, project_root: Path | None = None) -> str | None:
    """查找 ref 对应的 commit hash。如提供 project_root 则限定在该路径下。"""
    cmd = ["git", "log", "--oneline", f"--grep=ref: {ref}", "--format=%H", "-1"]
    if project_root:
        try:
            proj_rel = str(project_root.relative_to(git_root))
            cmd.extend(["--", proj_rel])
        except ValueError:
            pass
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=git_root)
    return r.stdout.strip() or None


# ═══════════════════════════════════════════════════════════════
# ID Management
# ═══════════════════════════════════════════════════════════════

def next_id(directory: Path, prefix: str) -> int:
    """扫描 {prefix}-NNN.md，返回下一个可用编号。"""
    if not directory.exists():
        return 1
    max_n = 0
    for f in directory.iterdir():
        m = re.match(rf"^{prefix}-(\d+)\.md$", f.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


# ═══════════════════════════════════════════════════════════════
# Templates
# ═══════════════════════════════════════════════════════════════

def source_body(n: int, title: str, content: str, participants: str, source_type: str) -> str:
    today = date.today().isoformat()
    return f"""---
id: S-{n:03d}
date: {today}
participants: {participants}
type: {source_type}
theme: {title}
---

# S-{n:03d}: {title}

> **日期**：{today}
> **参与者**：{participants}
> **类型**：{source_type}
> **主题**：{title}

---

{content}
"""


def refinery_body(n: int, title: str, content: str, sources: str, output: str, rtype: str) -> str:
    today = date.today().isoformat()
    src_list = ", ".join(s.strip() for s in sources.split(","))
    return f"""---
id: R-{n:03d}
date: {today}
type: {rtype}
sources: [{src_list}]
output: {output}
title: {title}
---

# R-{n:03d}: {title}

{content}
"""


# ═══════════════════════════════════════════════════════════════
# Source / Refinery CRUD
# ═══════════════════════════════════════════════════════════════

def add_source(project_root: Path, title: str, content: str,
               participants: str = "用户 + Dao",
               source_type: str = "dao-conversation",
               no_commit: bool = False) -> Path:
    sources_dir = project_root / ".sources"
    sources_dir.mkdir(exist_ok=True)

    n = next_id(sources_dir, "S")
    filepath = sources_dir / f"S-{n:03d}.md"
    filepath.write_text(source_body(n, title, content, participants, source_type), encoding="utf-8")

    _update_project(project_root)

    # git commit
    git_root = _git_root(project_root)
    if git_root and not no_commit:
        try:
            rel = str(filepath.relative_to(git_root))
        except ValueError:
            rel = None
        proj_rel = str((project_root / ".PROJECT.md").relative_to(git_root)) if (project_root / ".PROJECT.md").exists() else None
        for f in [rel, proj_rel]:
            if f:
                subprocess.run(["git", "add", "--", f], capture_output=True, cwd=git_root)
        subprocess.run(
            ["git", "commit", "-m", f"S-{n:03d}: {title}"],
            capture_output=True, cwd=git_root
        )

    return filepath


def add_refinery(project_root: Path, title: str, content: str,
                 sources: str, output: str = "",
                 rtype: str = "refinement",
                 no_commit: bool = False) -> Path:
    ref_dir = project_root / ".refineries"
    ref_dir.mkdir(exist_ok=True)

    n = next_id(ref_dir, "R")
    ref_id = f"R-{n:03d}"
    filepath = ref_dir / f"{ref_id}.md"
    filepath.write_text(refinery_body(n, title, content, sources, output, rtype), encoding="utf-8")

    _update_project(project_root)

    # git commit
    if not no_commit:
        commit_hash = _git_commit_refinery(project_root, ref_id, title, sources, output)
        if commit_hash:
            print(f"  git commit: {commit_hash[:7]}")

    return filepath


# ═══════════════════════════════════════════════════════════════
# PROJECT.md auto-update
# ═══════════════════════════════════════════════════════════════

def _count_entries(project_root: Path) -> tuple[int, int]:
    src_dir = project_root / ".sources"
    ref_dir = project_root / ".refineries"
    sc = len([f for f in src_dir.iterdir() if re.match(r"^S-\d+\.md$", f.name)]) if src_dir.exists() else 0
    rc = len([f for f in ref_dir.iterdir() if re.match(r"^R-\d+\.md$", f.name)]) if ref_dir.exists() else 0
    return sc, rc


def _update_project(project_root: Path):
    proj_file = project_root / ".PROJECT.md"
    if not proj_file.exists():
        return
    text = proj_file.read_text(encoding="utf-8")
    sc, rc = _count_entries(project_root)
    text = re.sub(r"(\| Sources\s+\| )\d+(\s+\|)", rf"\g<1>{sc}\g<2>", text)
    text = re.sub(r"(\| Refineries\s+\| )\d+(\s+\|)", rf"\g<1>{rc}\g<2>", text)
    proj_file.write_text(text, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
# Status / List
# ═══════════════════════════════════════════════════════════════

def _extract_title(filepath: Path) -> str:
    """从 Source/Refinery 文件中提取标题。跳过 YAML frontmatter。"""
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")
    in_frontmatter = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("# ")
        if stripped and not stripped.startswith(">"):
            return stripped
    return filepath.stem


def show_status(project_root: Path):
    _update_project(project_root)
    sc, rc = _count_entries(project_root)
    print(f"项目:   {project_root}")
    print(f"Sources:    {sc}")
    print(f"Refineries: {rc}")

    git_root = _git_root(project_root)
    if git_root:
        print(f"Git:        {git_root}")

    # 列出当前输出文件
    ref_dir = project_root / ".refineries"
    outputs = set()
    if ref_dir.exists():
        for f in sorted(ref_dir.glob("R-*.md")):
            text = f.read_text(encoding="utf-8")
            # 从 YAML frontmatter 提取 output 字段
            for line in text.split("\n"):
                if line.startswith("output:") or line.startswith("output: "):
                    val = line.split(":", 1)[1].strip()
                    if val:
                        outputs.add(val)
                    break
    if outputs:
        print("\n当前 Output 文件:")
        for o in sorted(outputs):
            op = project_root / o
            if op.exists():
                size = op.stat().st_size
                print(f"  {o}  ({size:,} bytes)")
            else:
                print(f"  {o}  (缺失)")

    src_dir = project_root / ".sources"
    if src_dir.exists():
        files = sorted(src_dir.glob("S-*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            print("\n最近 Source:")
            for f in files[:5]:
                print(f"  {f.name}  {_extract_title(f)}")


def list_entries(project_root: Path, entry_type: str):
    if entry_type in ("sources", "source", "s"):
        d, prefix = project_root / ".sources", "S"
    else:
        d, prefix = project_root / ".refineries", "R"

    if not d.exists():
        print("(空)")
        return

    for f in sorted(d.glob(f"{prefix}-*.md")):
        print(f"  {f.name}  {_extract_title(f)}")


# ═══════════════════════════════════════════════════════════════
# Output version management (git-style)
# ═══════════════════════════════════════════════════════════════

def output_log(project_root: Path, file_path: str | None):
    """展示 Output 的完整变更历史（git log + 标注 ref 版本）。"""
    git_root = _git_root(project_root)
    if not git_root:
        print("错误: 项目不在 git 仓库中，无法追溯 Output 版本", file=sys.stderr)
        sys.exit(1)

    # 先拿到该项目涉及的所有语义版本（ref-tagged commits）
    ref_commits = set()
    try:
        proj_rel = str(project_root.relative_to(git_root))
    except ValueError:
        proj_rel = "."
    r = subprocess.run(
        ["git", "log", "--grep=ref: R-", "--format=%H", "--", proj_rel],
        capture_output=True, text=True, cwd=git_root
    )
    if r.returncode == 0:
        ref_commits = {h.strip() for h in r.stdout.strip().split("\n") if h.strip()}

    # 完整 git log（不限制 ref 标签），标注 ref 版本
    fmt = "--format=%C(auto)%h %C(green)%ad %C(reset)%s"
    cmd = ["git", "log", fmt, "--date=short"]
    if file_path:
        full = str(project_root / file_path)
        try:
            rel = str(Path(full).relative_to(git_root))
        except ValueError:
            rel = file_path
        cmd.extend(["--", rel])

    r = subprocess.run(cmd, capture_output=True, text=True, cwd=git_root)
    if r.returncode != 0:
        sys.exit(r.returncode)

    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        # 提取 commit hash 短格式
        parts = line.split(None, 2)
        if len(parts) >= 1:
            short_hash = parts[0]
            # 查这个 commit 是否在 ref_commits 中
            full_r = subprocess.run(
                ["git", "rev-parse", "--verify", short_hash],
                capture_output=True, text=True, cwd=git_root
            )
            full_hash = full_r.stdout.strip()
            if full_hash in ref_commits:
                # 标注语义版本
                # 提取该 commit 的 ref 标签
                ref_r = subprocess.run(
                    ["git", "log", "-1", "--format=%B", short_hash],
                    capture_output=True, text=True, cwd=git_root
                )
                ref_line = ""
                for rl in ref_r.stdout.split("\n"):
                    if rl.startswith("ref: "):
                        ref_line = rl[5:].strip()
                        break
                marker = f" \033[1;33m[{ref_line}]\033[0m" if ref_line else ""
                print(f"{line}{marker}")
            else:
                print(line)


def output_show(project_root: Path, ref: str, file_path: str | None):
    """查看某 Refinery 时的 Output 快照。"""
    git_root = _git_root(project_root)
    if not git_root:
        print("错误: 项目不在 git 仓库中", file=sys.stderr)
        sys.exit(1)

    commit = _commit_for_ref(git_root, ref, project_root)
    if not commit:
        print(f"错误: 未找到 {ref} 对应的 git commit", file=sys.stderr)
        print(f"提示: 该 Refinery 可能未触发 git commit（没有产出文件变更）", file=sys.stderr)
        sys.exit(1)

    if file_path:
        # git show <commit>:<path> 需要相对于 git_root 的路径
        full_path = str(project_root / file_path)
        rel_to_git = str(Path(full_path).relative_to(git_root))
        subprocess.run(["git", "show", f"{commit}:{rel_to_git}"], cwd=git_root)
    else:
        subprocess.run(["git", "show", "--stat", commit], cwd=git_root)


def output_diff(project_root: Path, ref_from: str, ref_to: str, file_path: str | None):
    """对比两个 Refinery 版本之间的 Output 差异。"""
    git_root = _git_root(project_root)
    if not git_root:
        print("错误: 项目不在 git 仓库中", file=sys.stderr)
        sys.exit(1)

    c1 = _commit_for_ref(git_root, ref_from, project_root)
    c2 = _commit_for_ref(git_root, ref_to, project_root)
    if not c1:
        print(f"错误: 未找到 {ref_from} 的 git commit", file=sys.stderr)
        sys.exit(1)
    if not c2:
        print(f"错误: 未找到 {ref_to} 的 git commit", file=sys.stderr)
        sys.exit(1)

    cmd = ["git", "diff", f"{c1}..{c2}"]
    if file_path:
        cmd.extend(["--", file_path])
    subprocess.run(cmd, cwd=project_root)


def show_timeline(project_root: Path, file_path: str | None):
    """展示完整溯源时间线：Source → Refinery → Output 变更历史。"""
    print(f"\033[1;36m══════════ 溯源时间线: {project_root.name} ══════════\033[0m\n")

    sc, rc = _count_entries(project_root)

    # ── Sources ──
    print(f"\033[1;33m┌─ Sources ({sc}) ─────────────────────────────────────┐\033[0m")
    src_dir = project_root / ".sources"
    if src_dir.exists():
        for f in sorted(src_dir.glob("S-*.md")):
            title = _extract_title(f)
            print(f"\033[1;33m│\033[0m \033[32m{f.name}\033[0m  {title}")
    print(f"\033[1;33m└──────────────────────────────────────────────────────┘\033[0m\n")

    # ── Refineries ──
    ref_dir = project_root / ".refineries"
    if ref_dir.exists():
        refs = sorted(ref_dir.glob("R-*.md"))
        for f in refs:
            title = _extract_title(f)
            # 去重前缀：标题格式通常是 "R-NNN: 实际标题"
            if title.startswith(f"{f.stem}: "):
                title = title[len(f.stem)+2:]
            text = f.read_text(encoding="utf-8")
            # 提取 sources 和 output
            s_list = ""
            o_list = ""
            for line in text.split("\n"):
                if line.startswith("sources: "):
                    s_list = line.split(":", 1)[1].strip().strip("[]")
                if line.startswith("output: "):
                    o_list = line.split(":", 1)[1].strip()
            src_str = f"  ← {s_list}" if s_list else ""
            out_str = f"  → {o_list}" if o_list else ""

            # 找对应 git commit
            git_root = _git_root(project_root)
            commit_info = ""
            if git_root:
                ch = _commit_for_ref(git_root, f.stem, project_root)
                if ch:
                    commit_info = f"  [{ch[:7]}]"

            print(f"\033[1;34m▶ {f.stem}: {title}\033[0m")
            print(f"  {commit_info}{src_str}{out_str}")
        print()

    # ── Output 版本历史 ──
    if file_path:
        print(f"\033[1;35m┌─ 文件演进: {file_path} ──────────────────────────────┐\033[0m")
        output_log(project_root, file_path)
        print(f"\033[1;35m└──────────────────────────────────────────────────────┘\033[0m")
    else:
        print(f"\033[1;35m┌─ Output 变更历史 ───────────────────────────────────┐\033[0m")
        output_log(project_root, None)
        print(f"\033[1;35m└──────────────────────────────────────────────────────┘\033[0m")


# ═══════════════════════════════════════════════════════════════
# Init
# ═══════════════════════════════════════════════════════════════

def init_project(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".sources").mkdir(exist_ok=True)
    (directory / ".refineries").mkdir(exist_ok=True)

    proj_file = directory / ".PROJECT.md"
    if not proj_file.exists():
        proj_file.write_text(f"""# PROJECT

> 创建: {date.today().isoformat()}

## 溯源状态

| 类型 | 数量 | 明细 |
|:-----|:-----|:-----|
| Sources | 0 | |
| Refineries | 0 | |

## 核心文档链

```
.sources/ ─→ .refineries/ ─→ 最终文件
```
""", encoding="utf-8")
        print(f"已初始化: {directory}")
    else:
        print(f".PROJECT.md 已存在，跳过 (目录: {directory})")


# ═══════════════════════════════════════════════════════════════
# Content input helpers
# ═══════════════════════════════════════════════════════════════

def _get_content(args) -> str:
    """-c > -f > stdin"""
    if hasattr(args, 'content') and args.content:
        return args.content
    if hasattr(args, 'file') and args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read().rstrip()
    return ""


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def _resolve_file(project_root: Path, file_path: str | None) -> str | None:
    """将文件路径转为相对路径。"""
    if not file_path:
        return None
    # 直接在当前目录下查找，或返回原路径（让 git 报错）
    return file_path


def main():
    parser = argparse.ArgumentParser(
        description="TraceTool - 知识溯源 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  trace source add -t "约束的狭义定义" -c "讨论内容..."
  trace refinery add -t "提炼约束定义" -s S-001,S-002 -o "约束场与机械智能.md"
  trace status
  trace list sources
  trace log 约束场与机械智能.md
  trace show R-020
  trace diff R-015 R-020
  trace init ./my-project
""")
    parser.add_argument("-d", "--directory", help="项目根目录 (默认向上查找 PROJECT.md)")
    parser.add_argument("-q", "--quiet", action="store_true", help="只输出文件路径")
    parser.add_argument("--no-git", action="store_true", help="跳过所有 git commit（用于程序化调用）")

    sub = parser.add_subparsers(dest="command", help="子命令")
    ip = sub.add_parser("init", help="初始化溯源项目目录")
    ip.add_argument("target", nargs="?", help="目标目录 (默认当前目录)")

    # source add
    sp = sub.add_parser("source", help="Source 管理")
    sp_sub = sp.add_subparsers(dest="action")
    sa = sp_sub.add_parser("add", help="添加 Source")
    sa.add_argument("-t", "--title", required=True, help="标题")
    sa.add_argument("-c", "--content", help="正文内容")
    sa.add_argument("-f", "--file", help="从文件读取正文")
    sa.add_argument("--type", default="dao-conversation", dest="source_type")
    sa.add_argument("--participants", default="用户 + Dao")

    # refinery add
    rp = sub.add_parser("refinery", help="Refinery 管理")
    rp_sub = rp.add_subparsers(dest="action")
    ra = rp_sub.add_parser("add", help="添加 Refinery")
    ra.add_argument("-t", "--title", required=True, help="标题")
    ra.add_argument("-c", "--content", help="正文内容")
    ra.add_argument("-f", "--file", help="从文件读取正文")
    ra.add_argument("-s", "--sources", required=True, help="来源 Source (逗号分隔)")
    ra.add_argument("-o", "--output", default="", help="输出目标文件 (逗号分隔)")
    ra.add_argument("--type", default="refinement", dest="rtype")
    ra.add_argument("--no-commit", action="store_true", help="跳过 git commit")

    sub.add_parser("status", help="显示溯源状态")

    lp = sub.add_parser("list", help="列出条目")
    lp.add_argument("type", choices=["sources", "refineries"], nargs="?", default="sources")

    # output version management (top-level, git-style)
    olog = sub.add_parser("log", help="Output 版本历史")
    olog.add_argument("file", nargs="?", help="文件路径")

    oshow = sub.add_parser("show", help="查看某 Refinery 时的快照")
    oshow.add_argument("ref", help="Refinery 编号（如 R-020）")
    oshow.add_argument("file", nargs="?", help="文件路径")

    odiff = sub.add_parser("diff", help="两个版本间 diff")
    odiff.add_argument("ref_from", help="起始 Refinery（如 R-015）")
    odiff.add_argument("ref_to", help="终止 Refinery（如 R-020）")
    odiff.add_argument("file", nargs="?", help="文件路径")

    tl = sub.add_parser("timeline", help="完整溯源时间线")
    tl.add_argument("file", nargs="?", help="文件路径（可选，指定则只看该文件的演进）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # ── init ──
    if args.command == "init":
        target = Path(args.target) if args.target else Path.cwd()
        init_project(target)
        return

    # ── all other commands need a project root ──
    root = Path(args.directory) if args.directory else require_project()

    if args.command == "source" and args.action == "add":
        content = _get_content(args)
        fp = add_source(root, args.title, content, args.participants, args.source_type,
                        no_commit=args.no_git)
        if args.quiet:
            print(fp)
        else:
            print(f"已创建 Source: {fp}")

    elif args.command == "refinery" and args.action == "add":
        content = _get_content(args)
        fp = add_refinery(root, args.title, content, args.sources,
                          args.output, args.rtype, no_commit=args.no_git or args.no_commit)
        if args.quiet:
            print(fp)
        else:
            print(f"已创建 Refinery: {fp}")

    elif args.command == "status":
        show_status(root)

    elif args.command == "list":
        list_entries(root, args.type)

    elif args.command == "log":
        output_log(root, _resolve_file(root, args.file))

    elif args.command == "show":
        output_show(root, args.ref, _resolve_file(root, args.file))

    elif args.command == "diff":
        output_diff(root, args.ref_from, args.ref_to,
                    _resolve_file(root, args.file))

    elif args.command == "timeline":
        show_timeline(root, args.file)


if __name__ == "__main__":
    main()
