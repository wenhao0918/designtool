# TraceTool

知识溯源 CLI 工具。管理 Source → Refinery → Output 溯源链，自动化「知识溯源方法论 V0.1」中的文件约定与编号管理。

## 安装

```bash
# 添加到 PATH（可选）
alias trace="python $PWD/DesignTool/TraceTool/trace.py"
```

零外部依赖，Python 3.10+ 标准库即可运行。

## 快速开始

```bash
# 初始化溯源项目
trace init ./my-project

# 添加一条 Source（原始讨论记录）
trace source add -t "约束的狭义定义" -c "讨论内容..."

# 或从文件读取
trace source add -t "标题" -f /tmp/content.md

# 或通过管道
echo "内容..." | trace source add -t "标题"

# 添加一条 Refinery（提炼记录，同时自动 git commit 关联的 Output 文件）
trace refinery add -t "提炼约束定义" -s S-001,S-002 -o "约束场与机械智能.md" -c "提炼内容..."

# 跳过 git commit（纯思辨归档，不关联 Output 变更）
trace refinery add -t "纯思辨" -s S-001 --no-commit -c "..."

# 查看状态
trace status

# 列出条目
trace list sources
trace list refineries

# Output 版本管理（模仿 git）
trace log                     # 所有 Output 文件的语义版本历史
trace log 约束场与机械智能.md  # 指定文件的历史
trace show R-020              # 查看 R-020 时的 Output 快照（概览）
trace show R-020 约束场与机械智能.md  # 查看具体文件内容
trace diff R-015 R-020        # 两个版本间所有 Output 差异
trace diff R-015 R-020 约束场与机械智能.md  # 指定文件的差异
```

## 工作流

```
讨论产出 ─→ trace source add ─→ sources/S-NNN.md
                                     │
              trace refinery add ────┘  -o "论文.md"
                     │
                     ├── refineries/R-NNN.md（不可变）
                     └── git commit（ref: R-NNN）── 快照 Output
```

每次 `refinery add -o <文件>` 自动：
- 分配递增编号
- 生成 YAML frontmatter + 模板
- 更新 PROJECT.md 中的计数
- **git commit**：将 R-NNN.md 和 Output 文件一起提交，commit message 格式 `R-NNN: 标题`

之后即可：
- `trace log` — 回溯 Output 的完整演进历史
- `trace show R-NNN` — 回到那个版本时的文件内容
- `trace diff R-A R-B` — 精确看到两个版本之间改了什么

如果项目不在 git 仓库中，自动跳过 git commit（不影响其他功能）。也可用 `--no-commit` 显式跳过。

## 目录结构

```
项目根/
├── PROJECT.md          # 项目元信息（自动维护计数）
├── sources/            # S-NNN.md，不可变，只追加
├── refineries/         # R-NNN.md，不可变，指向 sources
└── output/             # 定型输出（手动维护，不在工具范围内）
```

## Source 模板

```markdown
---
id: S-027
date: 2026-08-07
participants: 用户 + Dao
type: dao-conversation
theme: 标题
---

# S-027: 标题

> **日期**：2026-08-07
> **参与者**：用户 + Dao
> **类型**：dao-conversation
> **主题**：标题

---

（用户提供的内容）
```

## Refinery 模板

```markdown
---
id: R-021
date: 2026-08-07
type: refinement
sources: [S-001, S-002]
output: README.md#某节
title: 标题
---

# R-021: 标题

（用户提供的内容——四段结构：命题/纳入/排除/打开）
```

## 迭代方向

- [ ] `trace edit S-001` — 打开已有条目编辑
- [ ] `trace graph` — 展示 Source→Refinery→Output 依赖图
- [ ] `trace memory` — 同步到 DAO memory 系统
- [ ] Refinery 写入时自动标注 Output 文档（`<!-- ref: R-NNN -->`）
- [ ] 内容校验（source 引用完整性、编号连续性）
