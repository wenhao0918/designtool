# GbstdService — 国标服务统一外壳(端口 8104,HTTP+MCP)

> 各类国标经**分类目录**统一服务。分类的标准形式:
> **dataset 指针(RAGFlow 知识库)+ 统一服务方法** `query(q, top_k) → hits`。
> 智能在库里,外壳只做 命名/路由/生命周期;分类之间零个性化行为。
> 定位:国标域由本服务承载;KnowledgeBase(8101) 仍是联邦入口(术语/物料代理)。

## 架构

```
GbstdService (8104)
├── catalog.py   分类目录(data/catalog.json)
│                条目={name,label,keywords,service,dataset_id,status}
│                SERVICES 注册表:service类型→检索实现(统一签名)
├── ragflow_client.py ragflow 方法实现(检索+建库)
├── router.py    查询→分类:显式参数 > 关键词计分 > 默认分类
└── api.py       HTTP+MCP;query 按分类声明的 service 分发
```

## 分类即插件

加一类国标 = catalog 登记一行 + 灌库:
- `service: "ragflow"`(默认)——向量检索,auto_create 自动建库
- 未来表格类标准可注册新方法类型(如 `table` 参数化查表),
  在 SERVICES 加一个同签名实现即可,**API 与消费方不变**

## API(MCP 工具同名)

| 端点 | 说明 |
|---|---|
| GET /api/gbstd/status | 分类统计 + RAGFlow 连通 |
| GET /api/gbstd/categories | 分类目录 |
| POST /api/gbstd/categories | 新增/更新分类;auto_create=true 自动建 RAGFlow 库 |
| POST /api/gbstd/query | 检索:{q, category?, top_k}——显式分类优先,空则路由,all 全分类联检 |

## 分类路由规则

1. 显式 `category` 参数直接路由(不做分类);
2. 无参数:按分类关键词计分,命中最多的分类胜出;
3. 全零分:落到默认分类 `draw`(当前唯一有内容的库),响应标记 `default`。

## 首批分类

| name | label | service | 状态 | 库 |
|---|---|---|---|---|
| draw | 制图与标注(42 册 GB/T 445x/180x/131…) | ragflow | active | 工程图纸国标(现有) |
| fasteners | 紧固件 | ragflow | active | 国标-紧固件(演示建库) |
| materials | 材料与牌号 | ragflow | planned | 建库后自动 active |
| safety | 安全与防护 | ragflow | planned | 同上 |

## 内容入库

- 制图类:`DraftEngine/draftengine/gbstd/collect.py push --category draw`(默认)
- 新分类:先 `POST /api/gbstd/categories` 建库,再把内容 md 上传该库
  (collect.py `--category` 会向本服务解析目标库)

## 启动

tmux: `cd GbstdService && python3 api.py --port 8104`
