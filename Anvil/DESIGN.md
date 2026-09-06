# Anvil 项目目录结构设计

> 每个设计项目是一个自包含的目录。拷贝目录就拷贝了全部历史和结果，不依赖外部数据库。

## 设计原则

1. **目录即数据库** — 文件系统本身是不可变序列化格式，删掉 JSON 不丢版本序列
2. **名称与标识解耦** — 用户看到中文名，磁盘用 UUID，重命名项目不破坏引用
3. **日志即历史** — 设计日志只追加不覆盖，每一步有唯一 step_id，可追溯到对应结果文件
4. **内容寻址** — step_id 由参数快照的 hash 生成，相同操作产生相同 ID

## 目录结构

```
projects/                         ← 固定仓库位置
  {project_uuid}/                 ← 项目根（12 位 hex UUID）
    .design/                      ← 自包含元数据（类 .git）
      project.json                ← 自描述数据
      log                         ← append-only 结构化设计日志
    cad/                          ← CAD 文件
      {step_uuid}/                ← 每次 build 独立子目录
        design.step               ← 装配体 STEP
        design.stl                ← 合并 STL（3D 预览）
        {零件名}.stl              ← 按零件拆分
        manifest.json             ← 步骤快照 + 文件清单
    docs/                         ← 设计文档
    exports/                      ← 导出目录
    knowledge/                    ← 知识库
```

### `.design/project.json`

项目自描述数据。任何系统打开目录，读这个文件就知道是哪个项目。

```json
{
  "project_id": "a1b2c3d4e5f6",
  "name": "悬臂梁拓扑优化",
  "description": "...",
  "created_at": "2026-08-08T12:00:00",
  "updated_at": "2026-08-08T15:30:00",
  "schema_version": "1"
}
```

### `.design/log`

只追加的结构化设计日志。每一行是一条 JSON 记录。

```json
{"step_id":"create_20260808_120000_a1b2c3","action":"project_created","name":"悬臂梁拓扑优化","status":"ok","timestamp":"..."}
{"step_id":"build_a3f2e1d4c5b6_143022","action":"model_build","params_snapshot":{...},"result_dir":"a3f2e1d4c5b6_143022","status":"ok","timestamp":"..."}
```

### `cad/{step_uuid}/`

每次 model_build 生成一个独立子目录。目录名 = step_id，一一对应。

```
cad/
  a3f2e1d4c5b6_143022/          ← 第 1 次 build
    design.step
    design.stl
    底座.stl
    球体.stl
    manifest.json
  b7c8d9e0f1a2_150530/          ← 第 2 次 build
    ...
```

step_id 生成规则：`{content_hash}_{timestamp}`

- `content_hash` = SHA256(parts + joints 参数的排序 JSON) 前 12 位
- 相同参数 → 相同 hash → 可复现
- 加时间戳后缀以区分同参数多次构建

### `cad/{step_uuid}/manifest.json`

子目录内的自描述文件，记录构建时的完整快照。

```json
{
  "step_id": "a3f2e1d4c5b6_143022",
  "timestamp": "2026-08-08T14:30:22",
  "parts": [...],
  "joints": [...],
  "files": ["design.step", "design.stl", "底座.stl", "球体.stl"]
}
```

## 追溯链路

```
用户看到历史消息
  → 消息关联 step_id
    → .design/log 中查到对应记录
      → result_dir 指向 cad/{step_uuid}/
        → 打开目录下的文件
```

每一步都是确定性引用，不存在"猜"版本号。

## 向后兼容

旧项目（中文目录名 + `.anvil.json`）首次访问时自动迁移：

1. 生成 `.design/` 目录
2. 补充 `project_id`（写入 `.anvil.json` 和 `project.json`）
3. 写入迁移日志记录
4. 中文名路由继续可用

## API 路由

项目标识 `{project_ref}` 同时支持 project_id 和旧目录名：

```
GET  /api/projects                         → 项目列表（含 project_id + name）
POST /api/projects/create                  → 创建项目（返回 project_id）
GET  /api/project/{project_ref}/status     → 项目状态
GET  /api/project/{project_ref}/cad/       → CAD 文件列表（含子目录路径）
GET  /api/project/{project_ref}/cad/{path} → 下载文件（支持子目录路径）
```

前端使用 `project_id` 作为路由标识，显示 `name` 给用户。
