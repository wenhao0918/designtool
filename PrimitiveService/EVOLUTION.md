# EVOLUTION.md — PrimitiveService 自进化机制设计

> 状态：设计定稿待评审 · 2026-08-27
> 前提：原语已独立成服务（8103），Anvil 等为消费者。
> 目标（用户 2026-08-27 定，全自动边界）：
> 1. 跟踪使用者的使用日志，自动修复错误；
> 2. 发现有不能应对的，自动添加新原语并及时更新发布。

---

## 0. 核心判断

当前 PrimitiveService 的三个致命盲区：

| 盲区 | 现状代码 | 后果 |
|---|---|---|
| 无使用日志 | `api.py` 三端点调用即忘 | 不知道谁在用、怎么用、错在哪 |
| 缺口信号即弃 | `constraints.py` 检出 `unknown_primitive` 仅返回给调用方 | "不能应对"的证据没有积累 |
| 注册表是死的 | `registry.py` 硬编码字典 | 加原语必须改代码重启，谈不上"及时发布" |

自进化 = 把这三个盲区补成闭环：**信号 → 决策 → 变更 → 验证 → 发布 → 监控 → 回滚**。

```
┌───────────────────────────────────────────────────────────────┐
│                     信号层 usage_log.jsonl                     │
│   每次 list/validate/compose 全记录（含拒绝与失败）              │
└──────────────┬────────────────────────────┬───────────────────┘
               │                            │
      ┌────────▼─────────┐        ┌─────────▼────────┐
      │ 回路一：自动修复   │        │ 回路二：自动新增原语│
      │ 修规则不修模型     │        │ 缺口→生成→沙箱→注册│
      └────────┬─────────┘        └─────────┬────────┘
               │                            │
      ┌────────▼────────────────────────────▼───────┐
      │            发布层（动态注册表 + 版本 + 回归）   │
      │   golden 回归全绿 → 热加载 → 监控错误率 → 回滚  │
      └──────────────────────────────────────────────┘
```

---

## 1. 信号层：使用日志

### 1.1 记录点与格式

`api.py` 加 FastAPI 中间件，三个端点统一落 `data/usage_log.jsonl`：

```json
{
  "ts": "2026-08-27T10:30:00",
  "caller": "anvil|admin|external",          // X-Caller 头，缺省 external
  "endpoint": "compose",
  "parts_summary": {"shell_box": 1, "side_hole": 2},
  "joints_count": 1,
  "violations": [{"level": "hard", "rule": "blind_vs_wall", "part": "hole_1"}],
  "status": "ok|rejected|exec_error|timeout", // rejected=422硬律拒绝
  "duration_ms": 8200,
  "step_ok": true,                            // CADService 是否产出 STEP
  "err_fingerprint": "FreeCAD: BRep_API",     // stderr 首行前120字符
  "req_hash": "a3f2e1d4",                     // parts+joints 规范化哈希，聚类用
  "version": 7                                // 当时的注册表版本
}
```

关键原则：**被拒绝的请求比成功的更有价值**。422 拒绝、exec_error、timeout 必须记录，这是回路的燃料。

### 1.2 缺口统计（gap_stats）

`constraints.py` 的 `unknown_primitive` 违规不再返回即弃，由进化引擎聚合成 `data/gap_stats.json`：

```json
{
  "dovetail_slot": {
    "count": 6,
    "distinct_callers": 2,
    "first_seen": "...", "last_seen": "...",
    "sample_params": [
      {"name": "导轨滑槽", "L": 300, "W": 18, "H": 8, "t": 2}
    ],
    "status": "open|generating|shipped|needs_human"
  }
}
```

判定铁律：**同一未知 type 出现 ≥3 次（可配 `EVOLUTION_GAP_THRESHOLD`）= 真实能力缺口**。一次性的拼写错误不会触发（它们 count=1 且 req_hash 分散）。

---

## 2. 回路一：自动修复（修的是规则，不是模型）

修复对象是服务端资产，按风险从低到高分四类：

| 类型 | 触发信号 | 动作 | 风险 |
|---|---|---|---|
| R1 参数别名扩充 | `unknown_params` 违规中同一参数名聚集 | `_PARAM_ALIASES` 自动追加映射 | 极低（纯改名） |
| R2 hint 改写 | 同一 hard 规则违规复发 ≥5 次 | LLM 改写 hint 文案，附失败反例 | 低（只影响提示） |
| R3 description 加负例 | 用某原语后紧跟违规的比率 >30% | 该原语 description 追加反例示例 | 低 |
| R4 代码生成 bug | `exec_error` 的 err_fingerprint 聚集 ≥3 次 | LLM 定位 registry 生成函数 → 补丁 | 中（须沙箱验证） |

### 2.1 修复流程（以 R4 为例）

```
err_fingerprint 聚集 → 取 3 个完整失败样本
  → LLM 诊断 + 生成补丁（只允许改 registry.py 单个 generate_* 函数）
  → 沙箱：失败样本重放 + golden 回归
  → 全绿 → 写 data/patches/P-0042.json（含 diff、动机、样本哈希）
  → 应用 + reload + version+1
  → 任一红 → 丢弃补丁，指纹进黑名单（同指纹不再自动重试）
```

### 2.2 R1 的安全性说明

别名扩充是唯一**免沙箱**的修复：它只影响 `_normalize_params` 的参数改名，
改名后原语签名参数集不变，不可能改变几何语义。但仍记 patch 存档，可审计可回滚。

---

## 3. 回路二：自动新增原语

### 3.1 触发

- gap_stats 某条 count ≥ 阈值 且 status=open；
- 或 Anvil 侧 `comm.submit_gap` 的 pending_gap 队列（消费者主动报告，与被动信号互补）。

### 3.2 生成管线

```
1. 参数归纳：从 sample_params 提取公共参数名/类型/取值域 → schema 草案
2. LLM 生成：一个完整 registry 条目，强制模板：
   fn(name, <params>, pos=(0,0,0)) → return FreeCAD 代码字符串
   约束：纯字符串构造、禁 import、禁文件/网络操作
3. 测试用例生成（≥5 个）：
   - 全部来自真实 sample_params（用户真实意图）
   - + 边界值用例（最小尺寸、极端比例）
4. 沙箱验证（逐用例调 CADService）：
   ✅ STEP 产出  ✅ 体积 > 0  ✅ bbox 三维有限
   ✅ 现有 constraints.validate 无 hard 违规
   ✅ 生成代码可被 FreeCAD 重新加载（非一次性垃圾几何）
5. 通过 → data/primitives/dovetail_slot.json 落盘 → status=shipped
   失败 → 重试 ≤2 次（换 prompt 策略）→ 仍败 → needs_human
```

### 3.3 动态原语文件格式

```json
{
  "type": "dovetail_slot",
  "version": 1,
  "created_by": "evolution@tick-20260827-1030",
  "origin": {"gap_count": 6, "sample_req_hashes": ["a3f2", "b7e1"]},
  "description": "燕尾槽...（LLM 生成，含负例）",
  "params": {"L": "长度mm", "W": "槽宽mm", "t": "壁厚mm"},
  "fn_source": "def generate_dovetail_slot(name, L, W, H, t, pos=(0,0,0)):\n ..."
}
```

---

## 4. 发布层：动态注册表 + 热加载 + 回滚

### 4.1 注册表改造（registry.py）

```python
PRIMITIVE_REGISTRY = {}          # builtin: 现有 18 个硬编码条目
DYNAMIC_DIR = "data/primitives"  # 动态条目

def load_dynamic():              # 启动 + reload 时调用
    # 逐个加载 *.json，exec(fn_source) 受限执行：
    # 校验 fn 签名含 name/pos、源码无 import/open/exec/network 关键字
    # 失败的单条跳过并告警，不影响其他条目
```

`list_primitives()` 对消费者无感知——动态原语自动出现在清单里，**任何 LLM 下一次调用即获得新能力，这就是"及时更新发布"**。

### 4.2 版本与回滚

- `version` = 单调递增整数，每次 reload +1，随每个 API 响应头 `X-Primitives-Version` 下发；
- 每个动态原语文件带 `version` 字段，同一 type 更新即 +1；
- **回滚**：删除/改名对应 json + reload 即回滚到 builtin 态；
- **自动回滚**：发布后 30 分钟窗口内，该 version 下的 compose 错误率 > 基线 ×3 → 自动卸载最新动态原语并告警（全自动模式的安全网）。

### 4.3 golden 回归集

`data/golden/` 存历史成功案例的采样（parts/joints + 期望体积/bbox 容差），
保留最近 100 个、每原语至少 3 个。**任何 patch/新原语发布前必须全绿**，这是全自动边界的底线。

---

## 5. API 变更清单

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/primitives/list` 等 | - | 响应加 `X-Primitives-Version` 头 |
| `/api/evolution/gaps` | GET | 缺口统计（admin 观测） |
| `/api/evolution/tick` | POST | 手动触发一轮进化（token 保护），tmux cron 每 10 分钟自动调 |
| `/api/evolution/report` | GET | 最近修复/新增/回滚/needs_human 清单 |
| `/api/primitives/reload` | POST | 热加载（内部，token 保护） |

## 6. 文件布局

```
PrimitiveService/
├── registry.py          # +动态加载/受限 exec/版本
├── constraints.py       # unknown_primitive 信号上抛（不动校验逻辑）
├── evolution.py         # 进化引擎（新增，~300行）
├── api.py               # +usage 中间件 +evolution 路由
└── data/
    ├── usage_log.jsonl  # 滚动，单文件 >50MB 轮转
    ├── gap_stats.json
    ├── primitives/      # 动态原语 *.json
    ├── patches/         # P-XXXX.json 修复存档
    └── golden/          # 回归集
```

## 7. 全自动边界的三道闸

1. **沙箱必过**：一切变更（含别名外的修复）必须通过失败样本重放 + golden 回归；
2. **频控**：单次 tick 最多 1 个新原语 + 3 个补丁，防止进化引擎失控连环变更；
3. **黑名单**：回滚过的生成方案/错误指纹不再自动重试，needs_human 队列留给开发侧。

## 8. 落地路径

- **P0**（先有眼睛）：usage 中间件 + gap_stats + R1 别名自动扩充 + version/reload
- **P1**（再长手）：新原语生成管线 + 沙箱 + 动态发布 + golden 回归
- **P2**（后长脑）：R2/R3 hint 与 description 自改写 + 错误率自动回滚 + Anvil guardian.jsonl 联动（服务侧修复自动标记 Anvil 侧 open 问题为 resolved）

> 验收标准（对齐 DESIGN_PRIMITIVES.md 风格）：
> 用户连续两次报同一缺口 → 第二次时 list_primitives 已含该原语 → 架构成立；
> 依赖人工改代码发版 → 架构失败。
