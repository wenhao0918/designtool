# 知音 — 设计意图术语映射模块

> **知音**：让 AI 听懂设计师的语言。


## 一、模块定义

**知音** 是 DesignTool 工具链中的**语义理解层**。

它既不生成几何体，也不调用 FreeCAD，也不执行验证。它只做一件事：

> **接收设计师的自然语言表达 → 理解其真实设计意图 → 输出标准术语上下文（供 Anvil Agent 和 LLM 使用）**

名称取自《列子·汤问》伯牙子期典故——**伯牙弹琴，钟子期听；设计师说话，知音听。**


## 二、解决的核心问题

| 设计师说 | AI 可能理解成 | 知音 理解成 |
|:---|:---|:---|
| "打个眼儿" | 无匹配 / 报错 | "通孔"或"盲孔"（视上下文消歧） |
| "螺丝不能冒出来" | 字面含义 | "沉头孔" + 约束条件 |
| "这里要过根管子" | 无匹配 | "贯穿孔" + 孔径匹配管径 |
| "留点余量" | 无匹配 | "加工余量" + 公差建议 |
| "M6的螺丝孔" | "螺纹孔" | 完整意图："螺纹孔 + 标准件规格 + 深度/通孔判定" |
| "打4个，一圈" | 无匹配 | "圆周均布" + 数量 + 分度圆 |

**核心价值**：设计师不需要学习 FreeCAD 术语，不需要知道"盲孔"和"沉头孔"的区别，只需要说人话。


## 三、技术架构：三层存储

> 知音依赖三层存储体系，各有分工、互相补充。

### 3.1 三层存储定位

| 存储层 | 技术选型 | 存什么 | 为什么 |
|:---|:---|:---|:---|
| **数据库（结构化存储）** | MySQL（JSON 字段） | 术语的**结构化信息**：标准名称、定义、约束条件、几何映射参数、层级关系（父子/等价/关联） | 精确查询，保证工程数据的准确性 |
| **知识库（向量检索）** | RAGFlow（接口对接） | 术语的**描述性文本向量**：四层表达的完整语料库（L1-L4 的所有说法） | 模糊匹配，支持同义词/别名/口语化表达的语义检索 |
| **知识图谱** | RAGFlow（接口对接） | 术语间的**语义关系**：父子、等价、互斥、条件依赖 | 关系推理，支持消歧和上下文联想 |

### 3.2 为什么用 MySQL + RAGFlow？

| 存储层 | 技术选型 | 选型理由 |
|:---|:---|:---|
| **结构化数据** | MySQL | • 团队已有使用经验，运维成本低<br>• 术语表结构清晰，关系明确，天然适合关系型数据库<br>• JSON 字段支持灵活扩展（四层表达、映射参数）<br>• 事务支持保证数据一致性 |
| **语义检索 + 知识图谱** | RAGFlow | • 已部署 RAGFlow 服务，基础设施就绪<br>• 同时支持向量检索和知识图谱，一鱼两吃<br>• 通过 HTTP API 对接，不产生代码耦合<br>• 未来可平滑替换为其他 RAG 系统（接口层隔离） |

### 3.3 分层职责边界

```
┌─────────────────────────────────────────────────────────────────┐
│                     API 接口层                                 │
│              （知音 · 听 / 问 / 记）                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     检索路由层                                 │
│        根据查询类型，决定走哪一路或并行多路                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
        ┌────────────────────┼────────────────────┐
        ↓                    ↓                    ↓
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   数据库      │   │   知识库      │   │   知识图谱    │
│   (MySQL)    │   │  (RAGFlow)   │   │  (RAGFlow)   │
│               │   │               │   │               │
│ • 精确匹配    │   │ • 语义检索    │   │ • 关系推理    │
│ • 结构化查询  │   │ • 模糊匹配    │   │ • 关联推荐    │
│ • 偏好记忆    │   │ • 向量相似度  │   │ • 消歧辅助    │
└───────────────┘   └───────────────┘   └───────────────┘
```

**关键设计原则**：

- **RAGFlow 仅通过 HTTP API 访问**，不直接依赖 RAGFlow 的 Python SDK
- **所有 RAGFlow 调用封装在 `ragflow_client.py` 中**，未来更换 RAG 系统只需重写该文件
- **RAGFlow 不可用时**，系统降级为数据库精确匹配 + 规则引擎，保证基本功能可用


## 四、功能架构

```
┌─────────────────────────────────────────────────────────────┐
│                     设计师输入                              │
│   "在这个面上打4个M6的螺丝孔，螺丝头不能冒出来"              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    知音 · 听                               │
│                语义理解引擎核心                             │
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  │
│  │  听 · 辨      │  │  听 · 问      │  │  听 · 谱      │  │
│  │ 四层表达匹配   │→│ 歧义消解引擎   │→│ 术语知识库    │  │
│  │ L1/L2/L3/L4  │  │ 主动反问生成   │  │ + RAGFlow    │  │
│  └───────────────┘  └───────────────┘  └───────────────┘  │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │                    知音 · 记                         │  │
│  │          对话上下文管理 · 用户偏好记忆                │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              输出：术语上下文（JSON）                        │
│                                                             │
│  {                                                          │
│    "terms": ["沉头孔", "螺纹孔", "圆周均布"],               │
│    "definitions": { ... },                                  │
│    "mapping": { "geometry": "counterbore_hole" },           │
│    "constraints": [ "depth < wall_thickness" ],             │
│    "clarifying_questions": ["沉头深度未指定"]               │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
                              ↓
                    ┌─────────────────┐
                    │   Anvil Agent   │
                    │  （任务编排）    │
                    └─────────────────┘
```


## 五、核心能力

### 5.1 四层表达映射（知音 · 辨）

| 层级 | 说明 | 示例 |
|:---|:---|:---|
| **L1 标准术语** | 机械设计规范用语 | "沉头孔"、"贯穿孔"、"螺纹孔" |
| **L2 行业俗称** | 同义词、简称、方言 | "沉眼"、"螺丝窝"、"埋头眼" |
| **L3 动词化表达** | 操作导向的口语 | "打沉头"、"扩一下"、"铣个坑" |
| **L4 意图性表达** | 目的导向的描述 | "螺丝不能冒出来"、"要平的" |

### 5.2 歧义消解引擎（知音 · 问）

当一条输入匹配到多个可能的术语时，知音 会：

1. **利用上下文消歧**（如"螺丝孔"在前文提到"表面要平"时，倾向"沉头孔"）
2. **利用设计场景消歧**（如"安装法兰"场景下，"螺丝孔"倾向"通孔"）
3. **利用用户偏好消歧**（如果用户习惯用"螺丝孔"指"螺纹孔"，记住它）
4. **无法消歧时主动反问**（生成澄清问题返回给前端）

### 5.3 术语知识库（知音 · 谱）

| 存储层 | 技术 | 内容 |
|:---|:---|:---|
| **术语表** | MySQL | 结构化术语数据（定义、约束、映射） |
| **别名索引** | MySQL（JSON 字段） | 四层表达的完整索引 |
| **语义向量** | RAGFlow | L2/L3/L4 表达的向量化表示 |
| **语义图谱** | RAGFlow | 术语间关系、语义相似度匹配 |

### 5.4 上下文管理（知音 · 记）

- **会话上下文**：单次对话中的前文引用
- **用户偏好**：跨会话记住个人表达习惯
- **场景记忆**：记住当前设计场景（"我们在设计法兰"）


## 六、检索机制：分阶段渐进式检索

> 知音的检索不是一次完成的，而是分阶段、渐进式的，保证召回率和精确率。

### 6.1 检索流程图

```
┌─────────────────────────────────────────────────────────────┐
│                   设计师输入                                │
│   "用M8螺丝固定，不要冒出来"                              │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    第一阶段：命名实体识别（NER）            │
│                                                             │
│   "用 M8 螺丝 固定，不要 冒出来"                          │
│       ↑     ↑      ↑         ↑                             │
│     规格  紧固件  动作      意图                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    第二阶段：多路召回                       │
│                                                             │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│   │  MySQL精确   │  │ RAGFlow语义  │  │ RAGFlow图谱  │   │
│   │  匹配（L1）  │  │ 匹配（L2/L3）│  │  推理（L4）  │   │
│   └──────────────┘  └──────────────┘  └──────────────┘   │
│         ↓                  ↓                  ↓             │
│     "螺丝→螺栓"      "不要冒出来→沉头"   M8→配套通孔Φ8.5  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    第三阶段：融合排序                       │
│                                                             │
│   候选结果：                                                │
│   1. "沉头孔" → 置信度 0.85（来源：RAGFlow语义 + 图谱）   │
│   2. "螺纹孔" → 置信度 0.70（来源：MySQL精确匹配）         │
│   3. "通孔"   → 置信度 0.50（来源：RAGFlow图谱推理）       │
│                                                             │
│   综合判断：选择"沉头孔" + 待确认"沉头深度"                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    第四阶段：主动反问（如需要）             │
│                                                             │
│   "您说的是沉头孔吗？请确认沉头深度（默认为螺丝头厚度+0.5mm）"│
└─────────────────────────────────────────────────────────────┘
```

### 6.2 检索策略优先级

| 优先级 | 检索路径 | 存储层 | 适用场景 | 速度 |
|:---|:---|:---|:---|:---|
| **P0** | L1 精确匹配 | MySQL | 设计师使用标准术语（如"沉头孔"） | 最快 |
| **P1** | L2 别名检索 | MySQL | 设计师使用行业俗称（如"沉眼"） | 快 |
| **P2** | L3 语义检索 | RAGFlow | 设计师用操作描述（如"打沉头"） | 中等 |
| **P3** | L4 意图推理 | RAGFlow 图谱 | 设计师用目的描述（如"不要冒出来"） | 较慢 |
| **P4** | 关系推理 | RAGFlow 图谱 | 关联推荐（如"M8螺栓"→推荐孔） | 较慢 |

### 6.3 RAGFlow 接口抽象层

> 所有 RAGFlow 调用通过统一接口隔离，未来更换 RAG 系统只需实现同接口。

```python
# zhiyin/rag/interface.py

from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class RAGClientInterface(ABC):
    """RAG 系统统一接口"""
    
    @abstractmethod
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """语义检索：输入自然语言，返回相关术语及相似度"""
        pass
    
    @abstractmethod
    def graph_query(self, entity: str, relation: Optional[str] = None) -> List[Dict]:
        """知识图谱查询：输入实体，返回关联关系"""
        pass
    
    @abstractmethod
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """混合检索：语义 + 图谱，综合召回"""
        pass


# zhiyin/rag/ragflow_client.py

class RAGFlowClient(RAGClientInterface):
    """RAGFlow 实现"""
    
    def __init__(self, base_url: str, api_key: str, collection_id: str):
        self.base_url = base_url
        self.api_key = api_key
        self.collection_id = collection_id
    
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """调用 RAGFlow 的 /api/v1/retrieval 接口"""
        # HTTP 请求实现...
        pass
    
    def graph_query(self, entity: str, relation: Optional[str] = None) -> List[Dict]:
        """调用 RAGFlow 的知识图谱查询接口"""
        pass
    
    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """调用 RAGFlow 的混合检索接口"""
        pass
```


## 七、输出格式

### 核心输出：术语上下文（供 LLM 注入）

```json
{
  "terms": {
    "identified": ["沉头孔", "螺纹孔", "圆周均布"],
    "resolved": {
      "沉头孔": {
        "standard_term": "沉头孔",
        "definition": "上部为锥形或柱形沉头凹坑、下部为通孔的阶梯孔，用于容纳螺钉头部使其不突出表面",
        "category": "hole",
        "mapping": {
          "type": "counterbore_hole",
          "params": {
            "large_diameter": "fastener_head_diameter + clearance",
            "large_depth": "fastener_head_thickness + clearance",
            "small_diameter": "fastener_shank_diameter + clearance",
            "through": true
          }
        },
        "constraints": [
          "large_diameter >= fastener_head_diameter + 0.5",
          "large_depth >= fastener_head_thickness + 0.5",
          "depth < wall_thickness"
        ],
        "related_terms": ["螺栓", "通孔", "锪平"]
      }
    }
  },
  "ambiguous_terms": [],
  "clarifying_questions": [],
  "context": {
    "scene": "flange_mounting",
    "fastener_spec": "M6",
    "count": 4,
    "pattern": "circular",
    "pcd": 100
  },
  "confidence": 0.92
}
```


## 八、基础数据采集

### 8.1 数据来源

```
┌─────────────────────────────────────────────────────────────┐
│                    数据来源                                │
├─────────────────────────────────────────────────────────────┤
│ 1. 机械设计标准文档                                        │
│    → ISO/GB 标准全文 → 提取术语、定义、约束               │
│                                                             │
│ 2. 已有术语表                                              │
│    → 已整理的孔类术语表 → 直接导入                           │
│                                                             │
│ 3. 设计手册                                                │
│    → 《机械设计手册》《机械工程师手册》→ 补充术语库        │
│                                                             │
│ 4. 设计师真实对话日志                                      │
│    → 收集设计师与AI的对话 → 提取新说法 → 入库             │
│                                                             │
│ 5. 设计图纸和BOM表                                         │
│    → 从已有图纸中提取术语、标注、配合关系                  │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 数据采集优先级（分阶段）

| 阶段 | 采集内容 | 优先级 | 数据量目标 |
|:---|:---|:---|:---|
| **P0** | 孔类术语表（首批） | 最高 | 已就绪 |
| **P1** | 紧固件（螺栓/螺母/垫圈） | 高 | 50+ 术语，200+ 别名 |
| **P1** | 轴/孔配合 | 高 | 30+ 术语，100+ 别名 |
| **P2** | 螺纹标准 | 中 | 20+ 术语，80+ 别名 |
| **P2** | 齿轮/链轮 | 中 | 30+ 术语，80+ 别名 |
| **P3** | 材料/热处理 | 低 | 50+ 术语 |
| **P3** | 公差/表面粗糙度 | 低 | 30+ 术语 |

### 8.3 术语采集模板

每个术语按**四层表达**采集：

```json
{
  "standard_term": "沉头孔",
  "definition": "上部为锥形或柱形沉头凹坑、下部为通孔的阶梯孔",
  "category": "hole",
  
  "L1_standard": ["沉头孔", "沉孔", "锥形沉头孔"],
  "L2_synonyms": ["沉眼", "螺丝窝", "埋头孔", "喇叭孔", "锪平孔"],
  "L3_verb_forms": ["打沉头", "锪沉头", "铣沉头", "扩个沉头"],
  "L4_intent_patterns": ["螺丝不能冒出来", "不要凸起", "要平的", "藏住螺丝帽"],
  
  "negation_clues": ["不要沉头", "不用沉"],
  "ambiguity_friends": ["通孔", "螺纹孔"],
  "mapping": {
    "geometry": "counterbore_hole",
    "params": { "large_dia": "fastener_head_dia + 0.5", "depth": "head_thick + 0.5" }
  }
}
```


## 九、自进化机制

> 知音能"越用越懂你"，关键是建立"反馈闭环 + 方言吸收"机制。

### 9.1 反馈闭环

```
┌─────────────────────────────────────────────────────────────┐
│                    用户确认/纠正                           │
│                                                             │
│  知音输出："沉头孔，深度3mm"                              │
│  用户反馈："不对，我要的是贯穿孔"                         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    反馈记录                                 │
│                                                             │
│  记录这次纠正：输入"螺丝孔" + 语境"法兰安装" → 用户选了   │
│  "贯穿孔"而非"沉头孔"                                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    自动更新（三种策略）                     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 策略A：调整消歧规则                                │   │
│  │ → 在"法兰安装"语境下，"螺丝孔"优先匹配"贯穿孔"   │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 策略B：记录用户偏好（个性化）                      │   │
│  │ → User_A说"螺丝孔" = 贯穿孔（记住）              │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ 策略C：补充新表达（全局学习）                      │   │
│  │ → 如果多人说"螺丝孔"指贯穿孔，更新全局规则        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 方言采集系统

> "方言" = 设计师的个人表达习惯。知音需要识别、记录、适应每个用户的语言习惯。

```
┌─────────────────────────────────────────────────────────────┐
│                    方言采集                                 │
│                                                             │
│  来源：                                                    │
│  1. 用户与知音的对话历史                                   │
│  2. 用户对推荐结果的选择/纠正                             │
│  3. 用户手动录入的"我的常用语"                            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    方言分析                                 │
│                                                             │
│  例如：                                                    │
│  用户A：                                                  │
│    说"孔" → 90%指"通孔"                                 │
│    说"打眼" → 100%指"钻孔"                             │
│    说"沉" → 指"沉头孔"                                 │
│                                                             │
│  用户B：                                                  │
│    说"孔" → 80%指"螺纹孔"                              │
│    说"打眼" → 60%指"铰孔"                             │
│    说"沉" → 指"锪平"                                   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                    方言应用                                 │
│                                                             │
│  用户A下次说"打个孔"，知音自动理解为"通孔"              │
│  用户B下次说"打个孔"，知音自动理解为"螺纹孔"            │
│                                                             │
│  如果用户A在90%置信度下被打脸（用户说"我说的是螺纹孔"），│
│  系统根据本次纠正微调用户A的个人偏好参数                  │
└─────────────────────────────────────────────────────────────┘
```


## 十、数据模型（MySQL）

### 10.1 术语表

```sql
CREATE TABLE terms (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    term_id         VARCHAR(20) UNIQUE NOT NULL,    -- 'H_005'
    standard_term   VARCHAR(100) NOT NULL,          -- '沉头孔'
    definition      TEXT,                           -- 完整工程定义
    category        VARCHAR(50),                    -- 'hole', 'shaft', 'thread'
    sub_category    VARCHAR(50),                    -- 'fastener_hole'
    
    -- 四层表达（JSON 数组）
    l1_standard     JSON,                           -- ["沉头孔", "沉孔"]
    l2_synonyms     JSON,                           -- ["沉眼", "螺丝窝"]
    l3_verb_forms   JSON,                           -- ["打沉头", "锪沉头"]
    l4_intent_patterns JSON,                        -- ["螺丝不能冒出来"]
    negation_clues  JSON,                           -- ["不要沉头"]
    
    -- 映射与约束（JSON）
    mapping         JSON,                           -- 几何映射参数
    constraints     JSON,                           -- 约束规则
    default_fallback JSON,                          -- 默认行为
    
    -- 关联
    related_terms   JSON,                           -- ["螺栓", "通孔"]
    ragflow_graph_id VARCHAR(50),                  -- RAGFlow 图谱节点ID
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_category (category),
    INDEX idx_standard_term (standard_term),
    INDEX idx_term_id (term_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 10.2 别名索引表（用于快速检索 L2/L3/L4）

```sql
CREATE TABLE alias_index (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    expression      VARCHAR(200) NOT NULL,          -- "螺丝孔"
    term_id         VARCHAR(20) NOT NULL,           -- 指向 terms.term_id
    expression_type ENUM('L2', 'L3', 'L4') NOT NULL, -- 别名/动词/意图
    match_weight    DECIMAL(3,2) DEFAULT 1.00,      -- 匹配权重（越高越优先）
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_expression_type (expression, expression_type),
    INDEX idx_expression (expression),
    INDEX idx_term_id (term_id),
    FOREIGN KEY (term_id) REFERENCES terms(term_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 10.3 用户偏好表（方言/个性化）

```sql
CREATE TABLE user_preferences (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         VARCHAR(50) NOT NULL,
    expression      VARCHAR(200) NOT NULL,          -- "螺丝孔"
    resolved_term   VARCHAR(20) NOT NULL,           -- 该用户认为对应哪个术语
    confidence      DECIMAL(5,2) DEFAULT 0.70,      -- 置信度
    usage_count     INT DEFAULT 0,                  -- 使用次数
    last_used       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    PRIMARY KEY (user_id, expression),
    INDEX idx_user_id (user_id),
    INDEX idx_expression (expression)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 10.4 消歧规则表（从用户反馈中聚合）

```sql
CREATE TABLE disambiguation_rules (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    expression      VARCHAR(200) NOT NULL,          -- "螺丝孔"
    context         VARCHAR(200),                   -- "法兰安装"（NULL 表示全局）
    preferred_term  VARCHAR(20) NOT NULL,           -- 优先匹配的术语
    confidence      DECIMAL(5,2) DEFAULT 0.70,      -- 置信度（来自用户选择的统计）
    vote_count      INT DEFAULT 0,                  -- 被选择的次数
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_expression (expression),
    INDEX idx_context (context)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 10.5 新表达待审核表

```sql
CREATE TABLE pending_expressions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    expression      VARCHAR(200) NOT NULL,
    source_term     VARCHAR(20),                    -- 用户认为对应哪个术语
    source_user_id  VARCHAR(50),
    occurrence_count INT DEFAULT 1,
    status          ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
    
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_status (status),
    INDEX idx_expression (expression)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 10.6 RAGFlow 对接状态表（缓存语义检索结果）

```sql
CREATE TABLE ragflow_cache (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    query_hash      VARCHAR(64) UNIQUE NOT NULL,    -- MD5(query)
    query_text      TEXT NOT NULL,
    response        JSON,                           -- 缓存的检索结果
    hit_count       INT DEFAULT 0,                  -- 命中次数
    last_hit        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_query_hash (query_hash),
    INDEX idx_last_hit (last_hit)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```


## 十一、目录结构

```
Zhiyin/
├── readme.md
├── pyproject.toml
├── requirements.txt
│
├── zhiyin/
│   ├── __init__.py
│   ├── api.py                      # FastAPI 主入口
│   ├── engine.py                   # 语义理解引擎核心
│   ├── models.py                   # Pydantic 数据模型
│   ├── deps.py                     # 依赖注入
│   │
│   ├── listener/                   # 知音 · 听（核心匹配）
│   │   ├── __init__.py
│   │   ├── term_matcher.py         # L1/L2 精确匹配（MySQL）
│   │   ├── verb_matcher.py         # L3 动词匹配（MySQL + RAGFlow）
│   │   └── intent_matcher.py       # L4 意图匹配（RAGFlow 语义）
│   │
│   ├── questioner/                 # 知音 · 问（歧义消解）
│   │   ├── __init__.py
│   │   ├── context_analyzer.py     # 上下文分析
│   │   ├── rule_engine.py          # 规则消歧
│   │   └── clarification.py        # 反问生成
│   │
│   ├── lexicon/                    # 知音 · 谱（术语知识库）
│   │   ├── __init__.py
│   │   ├── term_db.py              # MySQL 访问
│   │   ├── alias_index.py          # 别名索引（内存缓存）
│   │   └── ragflow_client.py       # RAGFlow HTTP 客户端
│   │
│   ├── rag/                        # RAG 抽象接口层
│   │   ├── __init__.py
│   │   ├── interface.py            # RAGClientInterface 定义
│   │   └── ragflow_client.py       # RAGFlow 实现
│   │
│   └── memory/                     # 知音 · 记（上下文管理）
│       ├── __init__.py
│       ├── session_context.py      # 单次对话上下文
│       └── user_preferences.py     # 用户偏好记忆（MySQL）
│
├── data/
│   ├── terms/                      # 术语数据文件（导入用）
│   │   ├── holes.json
│   │   ├── shafts.json
│   │   ├── threads.json
│   │   ├── fits.json
│   │   └── fasteners.json
│   ├── aliases/                    # 别名索引（导入用）
│   │   └── alias_map.json
│   └── rules/                      # 消歧规则（导入用）
│       ├── ambiguity_rules.json
│       └── context_rules.json
│
├── scripts/                        # 工具脚本
│   ├── init_db.py                  # 数据库初始化
│   ├── import_terms.py             # 术语导入脚本
│   ├── sync_ragflow.py             # 同步数据到 RAGFlow
│   └── export_training_data.py     # 导出训练数据
│
└── tests/
    ├── test_listener.py
    ├── test_questioner.py
    └── test_integration.py
```


## 十二、API 接口

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| `POST` | `/api/listen` | **核心接口**：自然语言 → 术语上下文 |
| `POST` | `/api/question` | 生成澄清问题（歧义消解） |
| `POST` | `/api/resolve` | 歧义消解（单独调用） |
| `GET` | `/api/terms` | 列出所有术语（支持分类过滤） |
| `GET` | `/api/term/{id}` | 获取单个术语的完整定义 |
| `POST` | `/api/preferences` | 记录用户偏好（个性化） |
| `POST` | `/api/feedback` | 记录用户纠正反馈（自进化入口） |

### 核心接口定义

```python
# zhiyin/models.py

from pydantic import BaseModel
from typing import Optional, List, Dict

class ListenRequest(BaseModel):
    text: str                           # "在这个面上打4个M6的螺丝孔，螺丝头不能冒出来"
    scene: Optional[str] = None         # 设计场景，如 "flange_mounting"
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    previous_terms: Optional[List[str]] = []

class ListenResponse(BaseModel):
    terms: Dict[str, TermDefinition]    # 识别到的术语及完整定义
    ambiguous_terms: List[str]          # 待消歧的术语
    clarifying_questions: List[str]     # 需要反问的问题
    extracted_context: Dict             # 提取的上下文信息
    confidence: float                   # 0.0 ~ 1.0
    sources: List[str]                  # 来自哪一路检索（MySQL/RAGFlow）

class FeedbackRequest(BaseModel):
    session_id: str
    user_id: str
    original_text: str                  # 用户原始输入
    system_output: List[str]            # 知音输出的术语列表
    user_correction: str                # 用户的纠正（如"不是沉头孔，是贯穿孔"）
```


## 十三、启动与配置

### 13.1 环境变量

```bash
# MySQL 术语库
ZHIYIN_DB_HOST=localhost
ZHIYIN_DB_PORT=3306
ZHIYIN_DB_USER=zhiyin_user
ZHIYIN_DB_PASSWORD=xxx
ZHIYIN_DB_NAME=zhiyin_terms

# RAGFlow HTTP 接口
RAGFLOW_BASE_URL=http://localhost:9380
RAGFLOW_API_KEY=xxx
RAGFLOW_TERMS_COLLECTION=design_terms_2026
RAGFLOW_GRAPH_ID=design_graph_2026

# 服务端口
ZHIYIN_PORT=8081

# 缓存配置
RAGFLOW_CACHE_TTL=3600
```

### 13.2 启动命令

```bash
cd Zhiyin
pip install -e .
uvicorn zhiyin.api:app --host 0.0.0.0 --port 8081
```

### 13.3 初始化数据库

```bash
python scripts/init_db.py --host localhost --user zhiyin_user --password xxx
python scripts/import_terms.py --data data/terms/
python scripts/sync_ragflow.py --sync-terms --sync-graph
```


## 十四、开发路线图

| 阶段 | 内容 | 状态 |
|:---|:---|:---|
| **P0** | MySQL 表设计 + 初始化脚本 | 🔜 进行中 |
| **P0** | API 骨架 + 术语表导入（孔类术语） | 🔜 进行中 |
| **P1** | L1/L2 精确匹配器 + MySQL 集成 | 📋 待开发 |
| **P1** | RAGFlow HTTP 客户端封装 + 对接 | 📋 待开发 |
| **P2** | L3 语义检索（RAGFlow 向量） | 📋 待开发 |
| **P2** | L4 意图推理（RAGFlow 图谱） | 📋 待开发 |
| **P3** | 歧义消解引擎 + 反问生成 | 📋 待开发 |
| **P3** | 用户偏好记忆 + 方言采集 | 📋 待开发 |
| **P4** | 反馈闭环 + 自进化机制 | 📋 待开发 |
| **P4** | RAGFlow 缓存层 | 📋 待开发 |


## 十五、设计理念

> 伯牙弹琴，志在高山，钟子期曰："善哉！峨峨兮若泰山。"  
> 设计师说话，意在做沉头孔，知音听曰："善哉！此乃沉头孔也。"

**知音** 不做几何，不做验证。它只做一件事：**听懂设计师在说什么。**


## 十六、RAGFlow 对接方案

### 16.1 RAGFlow API 调用示意

```python
# zhiyin/rag/ragflow_client.py

class RAGFlowClient(RAGClientInterface):
    """RAGFlow HTTP 客户端"""
    
    def __init__(self, base_url: str, api_key: str, collection_id: str):
        self.base_url = base_url
        self.api_key = api_key
        self.collection_id = collection_id
        self.headers = {"Authorization": f"Bearer {api_key}"}
    
    def semantic_search(self, query: str, top_k: int = 5) -> List[Dict]:
        """语义检索：调用 RAGFlow 检索接口"""
        url = f"{self.base_url}/api/v1/retrieval"
        payload = {
            "collection_id": self.collection_id,
            "query": query,
            "top_k": top_k
        }
        response = requests.post(url, headers=self.headers, json=payload)
        return self._parse_response(response)
    
    def graph_query(self, entity: str, relation: Optional[str] = None) -> List[Dict]:
        """知识图谱查询：调用 RAGFlow 图谱查询接口"""
        url = f"{self.base_url}/api/v1/graph/query"
        payload = {
            "graph_id": self.graph_id,
            "entity": entity,
            "relation": relation
        }
        response = requests.post(url, headers=self.headers, json=payload)
        return self._parse_graph_response(response)
```

### 16.2 RAGFlow 数据同步脚本

```bash
# scripts/sync_ragflow.py

# 1. 从 MySQL 导出术语数据 → JSON
# 2. 调用 RAGFlow /api/v1/document/upload 导入术语文档
# 3. 调用 RAGFlow /api/v1/graph/node/create 创建图谱节点
# 4. 调用 RAGFlow /api/v1/graph/edge/create 创建图谱关系
```


## 十七、关键技术决策记录

| 决策点 | 选择 | 理由 |
|:---|:---|:---|
| **结构化存储** | MySQL | 团队已有经验，JSON 字段支持灵活扩展，事务保证一致性 |
| **语义检索** | RAGFlow（HTTP 接口） | 已部署 RAGFlow，通过接口对接可平滑替换 |
| **知识图谱** | RAGFlow（HTTP 接口） | 同上，复用基础设施 |
| **接口隔离** | RAGClientInterface 抽象类 | 未来更换 RAG 系统只需重写实现 |
| **缓存策略** | MySQL 缓存表 + TTL | 降低 RAGFlow 调用频率，控制成本 |


---

*知音 —— 让 AI 听懂设计师的语言。*

**版本**: 0.2.0  
**最后更新**: 2026-08-18