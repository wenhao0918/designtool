# SketchService — 绘图识别微服务

手绘草图 → 视觉模型识别 → 结构化设计意图，独立于 Anvil 运行。

## 架构

```
SketchPad (前端) → PNG + 场景描述
    → SketchService (:8096)
        → Vision LLM (OpenAI-compatible)
        → 设计意图 JSON {type, dimensions, features, description}
    → Anvil agent → FreeCAD 建模
```

## 文件

| 文件 | 说明 |
|:-----|:-----|
| `web.py` | FastAPI 服务入口，`POST /recognize`、`GET /health` |
| `recognize.py` | Vision 模型调用 + JSON 解析 |
| `document.py` | SketchDocument 数据结构（Python 端，与前端 types/sketch.ts 对称） |
| `.env` | LLM 配置（ANVIL_LLM_BASE_URL / API_KEY / MODEL） |
| `README.md` | 本文件 |

## 启动

```bash
cd DesignTool/SketchService
source .env
python3 -m uvicorn web:app --host 0.0.0.0 --port 8096
```

## API

### POST /recognize

multipart/form-data：
- `file`: PNG/JPEG 图片
- `template`: `"mechanical"` (默认)
- `prompt`: 可选的场景描述文本

返回：
```json
{
  "result": {
    "type": "零件类型",
    "dimensions": {"长": "200mm", "宽": "150mm"},
    "features": ["特征1", "特征2"],
    "description": "完整的设计意图描述",
    "suggested_name": "english_part_name"
  }
}
```

## 与 Anvil 的关系

Anvil 的 `/api/sketch` 是前端代理入口，实际识别由 SketchService 完成：

```
前端 POST /api/sketch (multipart)
    → Anvil web.py 代理
    → POST http://localhost:8096/recognize
    → SketchService 识别
    → 返回设计意图
    → Anvil 转成 agent 文本
    → agent 建模
```

SketchService 可以独立部署、独立扩容，Anvil 不直接依赖视觉模型。
