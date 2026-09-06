# Anvil — AI 机械设计 Agent

> 铁砧(Anvil)— 锻造的基座,一切成型从这里开始。

## 定位(三层战略)

Anvil 是 **Primordium 理论的验证场**与第一消费者:

```
Primordium(理论,持续演化)
  ↓ 形式化为设计原语体系(原语+约束+术语语义,独立服务规划中)
Anvil = 消费原语做设计 + 暴露理论缺陷(submit_gap)→ 回流理论修订
```

- 每次真实设计会话都在使用并验证当前理论,并直观演示其正确性与价值
- Anvil 之下,DesignTool 胶水层提供服务:CADService(FreeCAD 执行)/
  DraftEngine(出图)/kbservice(国标知识联邦)——Anvil 不自己造底层

## 它是什么

用自然语言描述需求,AI 完成:需求解析 → 概念设计 → 增量建模 → 强度校核 →
STEP/STL 交付。一个项目一个会话,多轮迭代修改不清空重建。

**知识驱动**:建模前查国标(query_standard),补全参数标注
`[依据 GB/T xxx]`;diff-aware 合规检查;设计语言沟通(不暴露工具名)。

## 架构

```
浏览器 (:5174/5175)
    │  /api/*
    ▼
Anvil API (:8095)
    ├── JWT 认证(AdminService :8097)
    ├── DesignAgent (LLM + tools + 国标知识库工具)
    ├── CADService (:8102, FreeCAD 统一执行,降级本地)
    ├── RAG 知识库(经 kbservice :8101 联邦)
    └── 项目数据(模型状态/设计日志/决策记录)

Sketch API (sketch-service :8096)
    └── Vision 模型识别
```

## 工具箱

| 工具 | 说明 |
|:----|:-----|
| **手绘草图** | 画板 + 8 种手势识别 + 语音，AI 从草图建 3D 模型 |
| **图元库** | 18 种设计原语（壳体/轴/孔/弹簧/齿轮…），拖放填参即建模 |
| **AI 对话** | 自然语言描述设计需求，AI 推理+ 建模 + 出文档，SSE 流式返回 |
| **3D 查看器** | Three.js 渲染 STEP/STL，hover tooltip + 旋转/缩放/自适应 |

### 手绘草图 (SketchPad)

~2000 行核心组件，是整个工具链的多模态输入入口。

**数据模型 — SketchDocument**：

草图不只是像素，是一个多维数据结构（`src/types/sketch.ts`）：

```
SketchDocument
├── meta          { scene, title, author, createdAt, modifiedAt }
├── layers[]      每层 { id, name, visible, locked, strokes[] }
├── shapes[]      { type, x, y, size, angle, category }
├── gestures[]    { gesture, x, y, note }
└── activeLayerId
```

**场景系统**（决定默认图层结构和语义）：

| 场景 | 默认图层 | 适用 |
|:-----|:--------|:-----|
| ⚙️ 机械设计 | 结构轮廓 / 标注尺寸 / 运动示意 / 批注 | 零件外形、装配关系、传动草图 |
| 🏛️ 建筑设计 | 墙体轴线 / 空间分区 / 标注 / 家具布置 | 功能分区、流线规划、立面草图 |
| 🎨 绘画 | 线稿(锁) / 底色 / 阴影 / 高光 | 分层上色、光影叠加 |
| 🎬 动漫 | 背景 / 角色 / 特效 / 注释 | 分镜草图、角色设定、场景构图 |

**绘制模式**：画笔 / 橡皮 / 框选 / 形状(矩形/椭圆/多边形/套索) / 组件放置

**22 种形状**（按类别）：
- 立体几何（斜二测）：立方体、长方体、球体、圆柱、圆锥、棱锥
- 平面几何：圆、矩形、三角形、菱形、正五边形、正六边形、直线、箭头
- 机械组件：齿轮、铰链、推杆、电机、轴承、丝杠、滑轨、滚轮

**手势识别**（8 种）：
`confirm` ✓ / `reject` ✕ / `select` ○ / `point` → / `erase` 〰 / `emphasize` = / `rotate` / `move`

**图层系统**：多图层独立可见/隐藏/重命名/删除，每层可赋予不同语义（内容/批注/评论/建议/标注）

**渲染架构**：
- 设计层（design canvas）：可缩放，斜二测绘制立体/平面/机械图形
- 表达层（sketch canvas）：固定坐标，所有可见图层笔迹叠层渲染
- 全量重绘策略：每次 `pointerDown` / `pointerMove` 遍历所有可见图层渲染，无 offscreen buffer

**平面化**：所有可见图层 + 设计层 → 合成 PNG，发送给 AI 视觉模型

**AI 理解管线**：
用户画 → `buildSceneDescription()` 生成结构化自然语言描述 + PNG → vision 模型 + Anvil agent → 机械设计建模

**持久化**：自动缓存到 localStorage（按项目隔离），刷新/重进自动恢复。手动保存/重绘/新建均支持。

**语音输入**：Web Speech API，实时转文字随草图发送给 AI。

**AI 集成**：点击发送 → 表达层+设计层合并为 PNG → 连同手势标签、组件列表、语音文本、颜色语义 → POST `/api/sketch`

## 项目结构

```
DesignTool/
├── frontend/                 # 统一前端
│   ├── src/
│   │   ├── api/index.ts     # API 层（JWT + fetch）
│   │   ├── stores/app.ts    # Pinia 全局状态
│   │   ├── types/sketch.ts  # SketchDocument 数据模型
│   │   ├── utils/gesture.ts # 手势识别算法
│   │   ├── components/      # UI 组件
│   │   └── views/           # 页面视图
│   ├── vite.config.ts       # proxy /api → Anvil :8095
│   └── package.json
├── Anvil/                    # AI 机械设计 Agent 后端
│   ├── anvil/
│   │   ├── web.py           # FastAPI 主入口（8095 端口）
│   │   ├── agent.py         # 核心 Agent（LLM + tools）
│   │   ├── auth.py          # JWT 认证
│   │   ├── db.py            # SQLite 数据库
│   │   ├── sketch.py        # Sketch API 客户端
│   │   ├── robot_tools.py   # 机器人运动学工具
│   │   ├── llm.py           # LLM 集成
│   │   ├── project/         # 项目管理
│   │   ├── tools/           # FreeCAD MCP / 图元 / 验证
│   │   ├── prompts/         # 系统提示词
│   │   └── rag/             # RAG 知识库
│   ├── projects/            # 项目数据
│   ├── .env                 # LLM 配置
│   └── start.sh
├── SketchService/            # 绘图识别服务
│   └── sketch.py            # Vision 识别 + 意图转 agent 文本
└── ParamDerive/              # 参数推导工具
```

## 启动

### 本地开发

```bash
# 后端
cd DesignTool/Anvil
source .env
python3 -m uvicorn anvil.web:app --host 0.0.0.0 --port 8095

# 前端
cd DesignTool/frontend
pnpm dev   # → http://localhost:5174
```

### 远端部署

```bash
# 服务器上使用 start.sh（自动加载 .env）
cd <repo>/Anvil
./start.sh   # nohup 启动 :8095
```

## API

| 端点 | 方法 | 认证 | 说明 |
|:-----|:-----|:----:|:-----|
| `/api/auth/login` | POST | — | 登录，返回 JWT |
| `/api/auth/me` | GET | JWT | 当前用户信息 |
| `/api/projects` | GET | JWT | 项目列表 |
| `/api/projects/create` | POST | JWT | 创建项目 |
| `/api/project/{name}` | DELETE | JWT | 删除项目 |
| `/api/project/{name}/status` | GET | JWT | 项目状态 |
| `/api/project/{name}/history` | GET | JWT | 对话历史 |
| `/api/project/{name}/docs` | GET | JWT | 文档树 |
| `/api/project/{name}/doc/{section}/{file}` | GET | JWT | 文档内容 |
| `/api/project/{name}/rules` | GET/PUT | JWT | 设计规则 |
| `/api/project/{name}/cad/` | GET | JWT | CAD 文件列表 |
| `/api/project/{name}/cad/{file}` | GET | JWT | 下载 CAD |
| `/api/primitives` | GET | JWT | 可用图元列表 |
| `/api/sketch` | POST | JWT | 提交草图（multipart） |
| `/api/chat` | POST | JWT | 发送设计对话（SSE） |

默认账号：`admin / anvil123`（部署后请立即修改密码）

## 技术栈

**后端**：Python 3.12 / FastAPI / SQLAlchemy / SQLite / python-jose (JWT)

**前端**：Vue 3 / TypeScript / Vite 5 / Pinia / Three.js

**AI**：OpenAI-compatible LLM / Function calling / SSE streaming

**外部依赖**：
- FreeCAD (MCP 建模执行)
- RAG (知识库检索)
- dtwin (数字孪生，可选外部服务)
- sketch-service (绘图识别微服务 :8096)

## Sketch 绘图识别服务

`DesignTool/SketchService/` — 独立于 Anvil 的绘图识别管道。

- `recognize_sketch(image_bytes, scene_text)` → vision 模型 → 结构化设计意图 JSON
- `sketch_to_message(intent)` → agent 可理解的建模指令文本
- Anvil 通过 `/api/sketch` 代理调用 sketch-service (:8096)
