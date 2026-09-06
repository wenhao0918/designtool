# 知音（Zhiyin）架构说明文档

版本: 1.0
日期: 2026-08-18

简介
----
本文件将 `DesignTool/Zhiyin` 的架构、检索流程、存储设计、容错策略、接口契约以及实施建议汇总为一份可直接交付的技术文档。目的是方便开发、评审与后续迭代。

主要目标
----
- 将设计师的自然语言表达精确映射为结构化术语上下文（供 Anvil Agent / LLM 使用）。
- 提供可观测、可替换的 RAG 接口层，降低对具体第三方实现（RAGFlow）的耦合。
- 在 RAG 服务不可用时，保证系统可降级为数据库 + 规则引擎继续工作。

总体组件
----
- API 层（知音 · 听 / 问 / 记）：对外暴露语义解析与交互能力。
- 检索路由层：根据输入类型选择或并行调用 MySQL / RAG 向量检索 / 图谱推理。
- 存储层：
  - MySQL（结构化术语表，JSON 字段保存四层表达索引）
  - RAG 服务（向量检索 + 知识图谱），当前部署为 RAGFlow，通过 HTTP API 对接
- 上下文管理：会话、用户偏好、场景记忆

三层存储与职责
----
- MySQL（P0、P1 精确检索）：存储标准术语、别名、映射参数与约束（JSON）。用于快速、确定性的匹配。
- RAG 向量检索（P2）：用于 L2/L3 表达的模糊匹配和同义词召回。
- RAG 知识图谱（P3/P4）：用于意图级别推理、关系查询与消歧辅助。

检索与解析流程（分阶段）
----
1. NER 与意图分解：从句子中抽取规格、紧固件、动作、意图等结构化片段。
2. 多路召回并行执行：
   - MySQL 精确 + 别名索引
   - RAG 向量语义检索
   - RAG 图谱查询（若需要）
3. 融合排序：合并候选、基于来源置信度与上下文加权，输出 top-N 候选。
4. 歧义消解：利用上下文、场景与用户偏好，或生成主动澄清问题。
5. 输出：统一 JSON 术语上下文，含 `terms` / `mapping` / `constraints` / `clarifying_questions` / `confidence`。

输出示例（示意）
----
```json
{
  "terms": ["沉头孔", "螺纹孔"],
  "resolved": {
    "沉头孔": { "mapping": {"type": "counterbore_hole", "params": {...} }, "constraints": [...] }
  },
  "clarifying_questions": ["沉头深度是否按标准值？"],
  "confidence": 0.92,
  "context": { "fastener_spec": "M6", "count": 4 }
}
```

接口契约（建议）
----
- `POST /zhiyin/interpret` 接口：接受自然语言输入与会话上下文，返回结构化术语上下文。
- 请求体（示意）：{ "text": "在这个面上打4个M6的螺丝孔，不要冒出来", "session_id": "...", "scene": "flange_mounting" }
- 返回体：上述 JSON 输出格式。

RAG 抽象接口建议（伪代码）
----
建议在 `zhiyin/rag/interface.py` 定义统一接口，所有外部 RAG 调用仅通过该接口：

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class RAGClientInterface(ABC):
    @abstractmethod
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        pass

    @abstractmethod
    def graph_query(self, entity: str, relation: Optional[str] = None) -> List[Dict]:
        pass

    @abstractmethod
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        pass

# 具体实现示例请放在 zhiyin/rag/ragflow_client.py
```

容错与降级策略
----
- 当 RAGFlow 不可用：路由层自动回退到 MySQL 精确匹配 + 规则引擎（优先 P0/P1），并向调用方返回较低置信度与推荐的澄清问题。
- 对 RAG 调用加入超时、重试与熔断机制；记录指标（调用成功率、平均延迟、置信度分布）。

自进化与反馈闭环
----
- 在每次交互记录用户确认/更正：当用户将解析结果修正为其它术语时，记录该映射与上下文用于离线学习/人工审核。
- 支持在线方言吸收：对高频未命中短语批量标注并导入 L2/L3 数据库。

实施检查点（待检查/实现的文件）
----
- zhiyin/readme.md （已存在，作为设计说明）
- zhiyin/rag/interface.py  （建议新增/核对）
- zhiyin/rag/ragflow_client.py  （实现 RAGFlow HTTP 客户端）
- zhiyin/context_manager.py  （实现会话/偏好/场景记忆）
- zhiyin/api.py  （实现 `POST /zhiyin/interpret`）

建议的下一步开发计划（短期）
----
1. 创建并实现 `RAGClientInterface` 与 `RAGFlowClient`（HTTP）。
2. 设计 MySQL 术语表 schema（示例：id, standard_term, category, json_expressions, mapping, constraints, created_by）。
3. 实现检索路由层与融合排序器（可用简单权重规则实现首版）。
4. 完成 `POST /zhiyin/interpret` 的端到端测试（包含 RAGFlow 模拟/降级场景）。
5. 添加监控与指标（RAG 调用成功率、延迟、parse accuracy）。

长期建议（可选）
----
- 建立自动标注流水线：从真实对话中抽取新 L2/L3 表达并进入人工审核队列。
- 用轻量模型在本地做部分 L3 提取（NER/slot-filling），减轻 RAG 查询频率。
- 将知识图谱可视化工具接入以便运维与术语治理。

附录：参考链接
----
- 设计说明（已阅读）: [DesignTool/Zhiyin/readme.md](DesignTool/Zhiyin/readme.md)

运行时默认端口（本地开发可覆写环境变量）
----
- MySQL: `3307` (可通过 `MYSQL_PORT` 环境变量覆盖)
- RAGFlow: `1800` (可通过 `RAGFLOW_BASE_URL` 环境变量覆盖，例如 `http://localhost:1800`)

----
作者: Zhiyin 架构审核助手
