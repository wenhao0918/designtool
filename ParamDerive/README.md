# ParamDerive — 参数推导工作台 (API + MCP)

从数学、物理、机械原理出发，对产品设计参数进行可追溯的推导与验证。

## MCP Server

```
端口: 18084
启动: cd /path/to/DesignTool/ParamDerive
      PD_MCP_PORT=18084 python3 -m paramderive.mcp_server
传输: SSE
```

## MCP 工具

| 工具 | 说明 |
|------|------|
| `derive_list_params` | 列出所有参数（按分类/置信度筛选） |
| `derive_get_param` | 查看单个参数完整推导链 |
| `derive_calc` | 执行推导脚本 |
| `derive_whatif` | 假设分析：改输入条件重算 |
| `derive_update_param` | 更新参数值（带审计日志） |
| `derive_list_scripts` | 列出可执行的推导脚本 |

## 参数注册中心

`registry/registry.yaml` — 所有参数统一注册
`registry/audit_log.md` — 参数变更审计日志

## 推导脚本

放在 `anatomy/scripts/` `mechanics/scripts/` `kinematics/scripts/` `components/scripts/`

每个脚本必须包含 `calc(**kwargs)` 函数，返回 dict。

## 置信度

| 等级 | 含义 |
|------|------|
| ***** | 样机实测 |
| ****  | 理论计算+标准校核 |
| ***   | 理论计算（未校核） |
| **    | 类比/经验值 |
| *     | 假设/待验证 |

## 接入 Anvil

在 Anvil agent 的 tools 列表中注册 `derive_*` 工具，LLM 可在设计过程中实时查询和调用参数推导。
