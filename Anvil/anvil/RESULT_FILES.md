# 设计结果文件管理规范（RESULT_FILES）

> 状态:生效(2026-08-15)
> 范围:Anvil `model_build` / `freecad_execute` 生成的所有 CAD 结果文件
> 用途:后续开发与审核以此规范为准。任何改动违反下列规则即视为回归缺陷。

---

## 五条规则

### 1. 只保留最终的设计结果文件
- 每轮 build 目录内**只允许**存在:
  - `design.step` — 最终几何(装配体或单件)
  - `design.stl` — 最终合并网格(前端 3D 查看)
  - `manifest.json` — 本轮零件/装配清单
- **禁止**逐零件 STL、中间体、Assembly 重复导出、`001` 后缀冲突文件。
- 实现位置:`anvil/tools/primitives.py` `generate_model_export`(STL 循环按 `TypeId == 'App::Part'` 跳过 Assembly;只写合并 `design.stl`)。
- 审核:build 目录 `ls` 应恰好为上述 3 个文件。

### 2. 多组件时,结果文件为装配图
- 多零件时 STEP 必须导出**装配结构**(`App::Part 'Assembly'` 包含所有最终零件),不是散件。
- 零件 Label 保留在 STEP 内,作为 PRODUCT 名称。
- 实现位置:`generate_model_export`(创建 Assembly → `Import.export(doc.Objects, design.step)`)。
- 审核:多组件 build 后,STEP 在 FreeCAD/查看器中应显示装配层级与各零件名。

### 3. 各组件命名要可读
- FreeCAD 内部对象名 = `{原语类型}_{序号}`(如 `sphere_0`、`subtract_4`),不再用 `obj_N`。
- 原始中文名(如「外球」「内球_减除」)保留在对象 **Label**,STEP 导出后作为零件名。
- 中间体(布尔工具的 base/tools)在导出前被移除,不出现在结果里。
- 实现位置:`primitives.py` `_ascii_alias(idx, ptype)` + `generate_model`(Label 恢复 + `_INTERMEDIATE_NAMES` 清理)。
- 审核:生成代码/STEP 内对象名可读,无 `obj_0` 这类匿名名。

### 4. 设计结果文件不覆盖;每轮日志有唯一 ID,独立目录保存结果文件
- 每次 build 生成唯一 `step_id = {内容hash12}_{YYYYMMDD_HHMMSS_mmm}`(毫秒级),**任何两次 build 都不会落入同一目录**。
- 结果保存于 `projects/{项目}/cad/{step_id}/`,与历史日志条目一一对应。
- `.design/log` 与 `.anvil_history.jsonl` 中的 `step_id` 均可定位到该目录。
- 实现位置:`anvil/model_state.py` `build()`。
- 审核:同内容连续 build 两次,应产生两个不同目录,旧目录不被覆盖。

### 5. 历史日志里的文件链接必须能找到当时的结果
- 历史/日志中记录的文件路径统一为**相对项目根**形式:`cad/{step_id}/design.step`。
- 前端加载历史消息时,把 `cad/{step_id}/file` 与 `/api/project/{id}/cad/` 列表**精确匹配**,指向「当时」那一轮,而不是同名最新文件。
- 兼容旧数据:历史里的绝对路径(`/mnt/.../cad/{step_id}/file`)在前端转换时提取 `cad/` 之后的部分。
- 实现位置:
  - `anvil/agent.py` `_to_rel()`(model_build / assistant 消息统一转相对路径)
  - `frontend/src/stores/app.ts` `selectProject`(路径转换 + 精确匹配)
  - `frontend/src/components/ChatArea.vue` `cadFilePath`(精确命中版本目录)
- 审核:对历史消息点击 3D/下载,应打开该条消息对应轮次的文件;多版本同名时各链接指向各自版本。

### 6. 每条设计日志是结构化数据(JSON Lines,五要素)
- `.design/log` 每行是**合法 JSON 对象**,统一 schema,供程序化审计/溯源。
- 每条日志的五要素:
  - `id` — 唯一 ID(`action_时间戳_随机`),程序可精确定位
  - `time` — ISO 时间
  - `action` — 事件类型(`user_message` / `assistant_response` / `model_build` / `tool_call` / ...)
  - `instruction` — **设计指示**:本次设计要做什么(用户原始输入 / 工具+参数描述)
  - `llm_response` — **LLM 回应**:模型对本次指示的推理/答复内容(工具调用前的内容 + 最终完整答复)
  - `output_dir` — **设计结果目录**(`cad/{step_id}`),有结果文件时填写
  - `result_log` — **设计结果日志**:状态 / 结果文件相对路径 / 版本 / 摘要(按 action 结构化)
  - `project_id` — 项目 ID(附加,便于检索)
- 各 action 填充规则:
  - `user_message`:instruction=用户输入
  - `tool_call`:instruction=工具+参数;llm_response=调用该工具前的 LLM 推理;result_log={tool, params, result}
  - `model_build`:instruction=最近用户指示;llm_response=生成前的 LLM 回应;output_dir=cad/{step_dir};result_log={status, files, version, step_id, summary}
  - `assistant_response`:llm_response=完整最终答复;result_log={files, build_versions}
- 实现位置:`anvil/project/manager.py` `append_log()`(统一补 id/time/project_id + instruction/output_dir/result_log 默认);`anvil/agent.py` 各日志点。
- 审核:`.design/log` 任一行可 `json.loads`,且每行都含上述五要素;`model_build` 条目 `output_dir` 应指向实际存在的 `cad/{step_id}` 目录,`result_log.files` 为相对路径。

---

## 数据流总览

```
model_build (model_state.build)
  → step_id = hash_YYYYMMDD_HHMMSS_mmm(唯一)
  → cad/{step_id}/design.step + design.stl + manifest.json(只留最终文件,装配体)
  → 日志:step_id + files(相对路径 cad/{step_id}/file)
  → 前端:历史消息 → 精确匹配 cad/{step_id}/file → 3D/下载可追溯
```

## 历史沿革
- 2026-08-14:修复「打开失败」(前端纯文件名 vs 后端版本目录路径)与「中间文件泛滥」(Assembly 被当零件导出,`001` 重复)。
- 2026-08-15:正式立规——唯一 step_id(毫秒级)、内部名可读化、历史相对路径可追溯。
