# PrimitiveService — 设计原语体系(端口 8103,HTTP+MCP)

> **Primordium 理论的可执行载体**(三层战略·能力层,2026-08-26):
> 原语注册表 + 约束规则(服务端强制) + 术语语义 = 理论当前快照。
> 任何 LLM/Agent 经此获得统一建模能力;Anvil 是第一消费者(验证场)。

## 架构

```
PrimitiveService (8103)
├── registry.py       18 原语注册表(参数schema+FreeCAD 代码生成)——迁自 Anvil
├── constraints.py    约束引擎:hard(几何硬律,拒建模)/feas/value 三级
└── api.py            HTTP+MCP(fastapi-mcp)
组合建模链:compose → 约束校验 → 生成代码 → CADService(8102)执行
```

## API(MCP 工具同名)

| 端点 | 说明 |
|---|---|
| GET /api/primitives/list | 原语清单+schema+语义(LLM 可读) |
| POST /api/primitives/validate | {parts, joints} → 违规清单(不建模) |
| POST /api/primitives/compose | 校验→代码→CADService→STEP/STL |

## 约束分级(对齐 Primordium 层级约束框架)

- **hard** 硬律:盲孔深度≥壁厚、布尔引用缺失等——违反则 compose 拒绝执行
- **feas** 可行性:未知原语/参数(将被忽略)
- **value** 价值:壁厚偏薄等工程惯例提示

规则随原语下沉到服务端(不留在 Agent prompt)——任何 LLM 用原语即自动合规。

## 启动

tmux: `cd PrimitiveService && python3 -m api --port 8103`
