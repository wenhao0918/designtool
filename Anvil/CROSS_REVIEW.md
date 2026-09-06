# Hermes - OpenCode 交叉评审工作流

> 建立时间: 2026-07-31
> 规则: Hermes 评审 OpenCode 的代码，OpenCode 评审 Hermes 的代码。各自用独立 git 身份提交。

---

## Git 账号

```
Hermes   → hermes@anvil.ai
OpenCode → opencode@anvil.ai
```

### 提交方式

```bash
# 在 Anvil 项目目录下：
hermes-commit "feat: 加数据库 + JWT 认证 + 登录页"
opencode-commit "fix: 修复 FreeCAD 导出 bug"
```

两个命令会自动 `git add -A` 并以对应身份提交。

### 查看交叉评审日志

```bash
git-log-cr
# 显示最近 20 次提交及各自作者
```

---

## 本次 Hermes 修改内容

### 新增文件

| 文件 | 说明 | 状态 |
|------|------|------|
| `anvil/db.py` | SQLAlchemy 引擎 + User/ProjectDB 模型 + 初始化 | ✅ 已部署 |
| `anvil/auth.py` | JWT 登录/认证 + API 依赖注入 | ✅ 已部署 |
| `frontend/src/components/LoginPage.vue` | 登录页面（用户名+密码） | ✅ 已构建 |
| `CODE_REVIEW.md` | 对 Anvil 全量代码的评审报告 | ⏳ 待 OpenCode 回应 |
| `.gitconfig-hermes` | Hermes git 身份配置 | ✅ |
| `.gitconfig-opencode` | OpenCode git 身份配置 | ✅ |
| `commit.sh` | 提交辅助脚本 | ✅ |

### 修改文件

| 文件 | 改动 |
|------|------|
| `anvil/web.py` | **P0 修复**: 修复了 CAD 路由冲突（list_cad/download_cad/view_cad 各走各的路由）；修复了 list_cad 硬编码绝对路径问题；**新增**: 所有 `/api/*` 路由加了 `Depends(get_current_user)` 认证保护；启动时自动 `init_db()` |
| `frontend/src/api/index.ts` | 新增 token 管理（localStorage）、auth header 自动注入到所有 API 请求、401 自动跳登录 |
| `frontend/src/App.vue` | 新增登录状态检测，未登录渲染 LoginPage，已登录渲染原有界面 |
| `frontend/src/components/TopBar.vue` | 新增退出按钮（🚪） |
| `pyproject.toml` | 新增 `[project.optional-dependencies] db` |
| `.gitignore` | 排除 `*.backup*`、`*.deprecated`、`anvil.db`、`node_modules` |

### 数据库

- **类型**: SQLite（`anvil/anvil.db`）
- **默认账号**: `admin` / `anvil123`
- **表**: `users` + `projects`（projects 表预留，尚未对接现有文件系统项目）
- **示例**: `curl -X POST http://localhost:8091/api/auth/login -d '{"username":"admin","password":"anvil123"}'`

### 依赖（已安装）

```bash
pip3 install sqlalchemy python-jose[cryptography] bcrypt
```

---

## 需要 OpenCode 做的事情

### P0: 评审我改的代码

读一下 `anvil/db.py`、`anvil/auth.py`、`anvil/web.py`，确认：
1. 认证逻辑没问题（JWT 校验、密码 hash）
2. 路由保护没遗漏（所有 `/api/*` 都加了 Depends）
3. 我修的 P0 路由冲突确实好了
4. 前端 auth header 注入方式是否合理

### P1: 确认未覆盖的 API

一些边缘 API 我可能漏了加认证，帮我检查 `web.py` 里是否所有 `/api/` 开头路由都有 `Depends(get_current_user)`。

### P2: projects 表对接

目前 `projects` 表只建了模型，还没有写对接代码（创建项目时写 DB、项目列表从 DB 读）。后续如果要从文件系统迁移到 DB，你来搞。

---

## 工作流规则

1. **谁改谁提交** — Hermes 改的代码用 `hermes-commit` 提交，OpenCode 改的用 `opencode-commit`
2. **交叉评审** — 每次 PR/提交后，另一方必须审阅
3. **CODE_REVIEW.md 更新** — 评审结果记录在此文件
4. **维护者决策** — 评审有分歧时，维护者最终拍板

---

*本文件由 Hermes 生成。OpenCode 审完后回应到 CODE_REVIEW.md。*
