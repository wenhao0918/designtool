"""Core agent — orchestrates LLM, tools, and project management."""

import os
import json
from .llm import chat
from .tools.freecad import FreeCADTool
from .tools.document import DocumentTool
from .tools import primitives
from .tools.kb import ALL_KB_TOOLS, query_standard, check_design_compliance
from . import spatial as spatial_tools
from .model_state import ModelState, ALL_MODEL_TOOLS
from .qledger import TOOL_Q_APPLY, Kernel
from .structure import TOOL_STRUCTURE_SEARCH, handle_structure_search
from .comm import ALL_COMM_TOOLS, request_tool, check_tool_status, ALL_LOOP_TOOLS, submit_gap, check_loop, submit_result
from .dtwin_client import ALL_DTWIN_TOOLS
from .material_client import ALL_MATERIAL_TOOLS, TOOL_IMPL as MATERIAL_TOOL_IMPL
from .robot_tools import ALL_ROBOT_TOOLS
from .review_manager import ReviewManager, ALL_REVIEW_TOOLS
from .workshop import WorkshopManager, ALL_WORKSHOP_TOOLS
from .prompts.templates.template_engine import match_template, list_templates, tool_def as tmpl_tool_def, tool_list_def as tmpl_list_def
from .memory import ALL_MEMORY_TOOLS, inject_context, save as mem_save, recall as mem_recall, list_keys as mem_list_keys
from .requirement_parser import parse_requirement, to_tool_definition as req_tool_def
from .pipeline import design_review_markdown
from anvil.rag import get_backend as get_rag_backend
from .project.manager import ProjectManager
from .project.history import DesignHistory
from .prompts.system import build_system_prompt


def _to_rel(paths, base=None):
    """Convert absolute result paths to project-relative form (cad/{step_id}/file).

    Keeps history/log links resolvable to the exact build round, independent of
    machine/deployment path.  Non-absolute paths are returned as-is.
    """
    out = []
    for p in paths or []:
        if os.path.isabs(p):
            try:
                out.append(os.path.relpath(p, base) if base else p)
            except Exception:
                out.append(p)
        else:
            out.append(p)
    return out



class DesignAgent:
    """AI mechanical design agent — engineer + secretary."""

    def __init__(self, project_dir, user_id=None):
        self.project_dir = project_dir
        self.user_id = user_id
        self.project = ProjectManager(project_dir)
        self.history = DesignHistory(project_dir)
        self.freecad = FreeCADTool(project_dir)
        self.docs = DocumentTool(project_dir)
        self.model_state = ModelState(project_dir)
        self.review_mgr = ReviewManager(project_dir)
        self.workshop_mgr = WorkshopManager(project_dir)
        self.rag = get_rag_backend()

        self.tools = [
            req_tool_def(),
            self._freecad_tool_def(),
            self._get_list_primitives_def(),
            self._get_design_sentence_def(),
            TOOL_Q_APPLY,
            TOOL_STRUCTURE_SEARCH,
            self._get_lookup_term_def(),
        ] + ALL_MODEL_TOOLS + ALL_COMM_TOOLS + ALL_LOOP_TOOLS + ALL_MEMORY_TOOLS + ALL_DTWIN_TOOLS + ALL_MATERIAL_TOOLS + ALL_KB_TOOLS + [tmpl_tool_def(), tmpl_list_def()] + ALL_REVIEW_TOOLS + ALL_WORKSHOP_TOOLS + ALL_ROBOT_TOOLS + [
            self._get_hinge_rotation_def(),
            self._get_bellows_compression_def(),
            self._get_cantilever_bending_def(),
            self._get_pin_shear_def(),
            self._get_ergonomic_def(),
            self._get_check_interference_def(),
            self._get_load_estimate_def(),
        ] + self.rag.get_tool_definitions() + [
            self._get_document_tool_def(),
            self._get_decision_tool_def(),
            self._get_changelog_tool_def(),
            self._get_calculation_tool_def(),
            self._get_design_log_rollback_def(),
        ]

        self.messages = [{"role": "system", "content": build_system_prompt()}]

        # 建模防呆:首次 model_add_part 前必须调用过 list_design_primitives
        # (治"模型能力测试"事故:LLM 凭记忆猜原语,拿 shell_box 硬凑空心球)
        self._primitives_listed = False

        # === 上下文管理(A1/A2):文件即记忆 ===
        # 模型真状态在 .model_state.json/STEP;对话上下文只是引导。
        # 重建 agent 时:system + 模型摘要 + 最近 K 轮对话 + 决策记录摘要,
        # 不再无限增长。老对话被 record_decision/record_calculation 的
        # 结构化落盘替代(AI 在生产过程中自己写好的摘要)。
        self._RECENT_TURNS = 5        # 保留最近几轮对话原文
        self._TOOL_RESULT_MAX = 2000  # 工具结果截断阈值(字符)
        self._restore_history()

        config = self.project.get_config()
        proj_name = config.get("name", "未命名")
        proj_phase = config.get("phase", "concept")
        proj_desc = config.get("description", "")
        context = "\n\n## 当前项目\n" + "- 名称: " + proj_name + "\n"
        context += "- 阶段: " + proj_phase + "\n"
        if proj_desc:
            context += "- 描述: " + proj_desc + "\n"
        self.messages[0]["content"] += context

        rules_file = os.path.join(project_dir, ".rules.md")
        if os.path.exists(rules_file):
            with open(rules_file, encoding="utf-8") as f:
                rules = f.read().strip()
            if rules:
                self.messages[0]["content"] += (
                    "\n\n## 用户设计规则（优先级最高，必须遵守）\n"
                    + rules
                )

        # Stage tracking
        self.design_stage = "parse"
        self.current_spec = {}
        self.current_concept = {}

        # 术语表入库(首次建表写种子;之后用户自助增改)
        try:
            from .prompts.mech_terms import ensure_table
            ensure_table()
        except Exception:
            pass

        # 会话连续性:加载上轮设计结果(模型状态文件 .model_state.json)
        # 设计=会话;除非用户明确"重新设计",后续指令一律是对已有设计的增量修改。
        ms = self.model_state.get_state()
        if ms.get("parts"):
            try:
                ms_summary = self.model_state.summary()
            except Exception:
                ms_summary = ""
            self.messages[0]["content"] += (
                "\n\n## 当前模型(上轮设计结果,已从 .model_state.json 加载)\n"
                "以下零件已存在于模型中。用户后续指令【默认】是对已有设计的修改"
                "(改尺寸/加零件/删零件/加孔等增量操作),"
                "除非用户明确说'重新设计/重来/从头开始',否则禁止清空重建。\n"
                + ms_summary
            )

        # Inject persistent memory into system prompt
        mem_context = inject_context()
        if mem_context:
            self.messages[0]["content"] += mem_context

    def _freecad_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "freecad_execute",
                "description": "Execute FreeCAD Python code and export STEP. "
                              "Only use this for custom geometry NOT covered by build_model + primitives. "
                              "Prefer build_model + design primitives whenever possible.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code using Part.makeXxx API."
                        }
                    },
                    "required": ["code"]
                }
            }
        }

    def _get_list_primitives_def(self):
        return {
            "type": "function",
            "function": {
                "name": "list_design_primitives",
                "description": "List all available parametric design primitives and their parameters. "
                              "Call this to see what building blocks are available.",
                "parameters": {"type": "object", "properties": {}}
            }
        }

    def _get_design_sentence_def(self):
        """设计语言句子的唯一建模入口:LLM 只翻译,计算归 8103 演算器。"""
        return {
            "type": "function",
            "function": {
                "name": "design_sentence",
                "description": "【唯一建模入口】把用户的设计需求翻译成设计语言句子(JSON)提交给计算单元。"
                               "句子结构: {lang:'dsl.v0', bodies:[{id,kind(sphere/cylinder/box),"
                               "参数(r/h/L/W/H), features:[{op:'shell',t:壳厚}]}], "
                               "relations:[{rel:'rests_on_centered',a,b}]}。"
                               "只允许使用文法表内的词汇——位置/贴合/居中等一律用 relations 表达,由计算单元解算,"
                               "禁止自己算坐标。提交后计算单元返回演算结果,再调用 model_build 出图。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sentence": {
                            "type": "object",
                            "description": "设计语言句子,lang 必须为 dsl.v0;词汇以 system prompt 文法表为准"
                        }
                    },
                    "required": ["sentence"]
                }
            }
        }

    def _get_hinge_rotation_def(self):
            return {
                "type": "function",
                "function": {
                    "name": "calc_hinge_rotation",
                    "description": "Calculate rotated position of a point around a hinge axis. "
                                  "General rotation kinematics for motion verification.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "hinge_pos": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] hinge pin center"},
                            "axis_dir": {"type": "string", "enum": ["x", "y"], "description": "Hinge axis direction"},
                            "angle_deg": {"type": "number", "description": "Rotation angle in degrees"},
                            "point": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] point to rotate"}
                        },
                        "required": ["hinge_pos", "axis_dir", "angle_deg", "point"]
                    }
                }
            }

    def _get_bellows_compression_def(self):
            return {
                "type": "function",
                "function": {
                    "name": "calc_bellows_compression",
                    "description": "Calculate distance change between two attachment points when a hinge rotates. "
                                  "For flexible-section length checks (bellows, seals, sliding covers).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "initial_length": {"type": "number", "description": "Bellows free length (mm)"},
                            "angle_deg": {"type": "number", "description": "Hinge rotation angle"},
                            "hinge_pos": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] hinge center"},
                            "attach_a": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] bellows attach on part A"},
                            "attach_b": {"type": "array", "items": {"type": "number"}, "description": "[x,y,z] bellows attach on part B"},
                            "axis_dir": {"type": "string", "enum": ["x", "y"], "description": "Hinge axis direction"}
                        },
                        "required": ["initial_length", "angle_deg", "hinge_pos", "attach_a", "attach_b"]
                    }
                }
            }

    def _get_cantilever_bending_def(self):
        return {
            "type": "function",
            "function": {
                "name": "calc_cantilever_bending",
                "description": "Simple cantilever beam bending check. "
                              "Use to verify wall thickness and structural safety.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "force_N": {"type": "number", "description": "Force at free end (N)"},
                        "length_mm": {"type": "number", "description": "Beam length (mm)"},
                        "width_mm": {"type": "number", "description": "Beam width (mm)"},
                        "height_mm": {"type": "number", "description": "Beam height / wall thickness (mm)"},
                        "E_MPa": {"type": "number", "description": "Young's modulus MPa (default 70000 for Al)"}
                    },
                    "required": ["force_N", "length_mm", "width_mm", "height_mm"]
                }
            }
        }

    def _get_pin_shear_def(self):
        return {
            "type": "function",
            "function": {
                "name": "calc_pin_shear",
                "description": "Hinge pin shear stress check. Verify pin diameter is adequate.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "load_N": {"type": "number", "description": "Total load on hinge (N)"},
                        "pin_r": {"type": "number", "description": "Pin radius (mm)"},
                        "pin_count": {"type": "integer", "description": "Number of pins (default 2)"},
                        "material": {"type": "string", "description": "steel_304 / steel_316 / aluminum_6061"}
                    },
                    "required": ["load_N", "pin_r"]
                }
            }
        }

    def _get_ergonomic_def(self):
        return {
            "type": "function",
            "function": {
                "name": "suggest_ergonomic_dimensions",
                "description": "Suggest ergonomic dimensions for seated product design "
                              "based on human body reference. Use when user doesn't specify exact sizes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "body_height_mm": {"type": "number", "description": "User height in mm (default 1700)"},
                        "body_weight_kg": {"type": "number", "description": "User weight in kg (default 75)"}
                    }
                }
            }
        }

    def _get_load_estimate_def(self):
        return {
            "type": "function",
            "function": {
                "name": "estimate_sitting_loads",
                "description": "Estimate buttock and thigh loads for seated design (chairs, seats, recliners). "
                              "Use to calculate structural requirements.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "body_weight_kg": {"type": "number", "description": "User body weight kg (default 75)"},
                        "thigh_ratio": {"type": "number", "description": "Fraction of weight on thighs (default 0.3)"}
                    }
                }
            }
        }

    def _get_check_interference_def(self):
        return {
            "type": "function",
            "function": {
                "name": "check_part_interference",
                "description": "Check if parts overlap using bounding box comparison. "
                              "Use before building model to catch layout issues.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "parts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "params": {"type": "object"}
                                }
                            },
                            "description": "Same format as build_model parts"
                        }
                    },
                    "required": ["parts"]
                }
            }
        }

    def _get_document_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "save_document",
                "description": "Save a design document.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "section": {"type": "string", "enum": ["notes", "decisions", "calculations", "changelog"]}
                    },
                    "required": ["title", "content"]
                }
            }
        }

    def _get_decision_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "record_decision",
                "description": "Record a design decision.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "decision": {"type": "string"},
                        "reason": {"type": "string"},
                        "impact": {"type": "string"}
                    },
                    "required": ["question", "decision", "reason"]
                }
            }
        }

    def _get_changelog_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "record_change",
                "description": "Record a design change.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "change": {"type": "string"},
                        "reason": {"type": "string"}
                    },
                    "required": ["change"]
                }
            }
        }

    def _get_calculation_tool_def(self):
        return {
            "type": "function",
            "function": {
                "name": "record_calculation",
                "description": "Record an engineering calculation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "formula": {"type": "string"},
                        "inputs": {"type": "object"},
                        "result": {"type": "string"},
                        "notes": {"type": "string"}
                    },
                    "required": ["title", "formula", "result"]
                }
            }
        }

    def _get_design_log_rollback_def(self):
        return {
            "type": "function",
            "function": {
                "name": "design_log_rollback",
                "description": (
                    "修正或删除设计历史中的某一步修改。仅当用户【明确】要求"
                    "「修正第 N 步」「删除第 N 步的修改」「回到第 N 步重新来」"
                    "「撤销第 N 步」等时调用;用户没有指定步骤时不要调用,"
                    "而是当作对当前模型的普通增量修改。"
                    "设计日志每行一步,序号从 1 开始(用户消息/工具调用/生成模型各算一步)。"
                    "调用后模型恢复到第 N 步【开始前】的状态,后续指令基于此状态增量修改。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seq": {"type": "integer", "description": "设计日志步骤序号(1-based)"}
                    },
                    "required": ["seq"]
                }
            }
        }

    def _get_lookup_term_def(self):
        return {
            "type": "function",
            "function": {
                "name": "lookup_term",
                "description": (
                    "查询机械设计专业术语的定义与建模指导(盲孔/通孔/贯穿/相贯/沉孔/"
                    "阶梯孔/倒角/壁厚/轴向/径向等)。用户指令中出现不确定含义的专业术语时,"
                    "先调用此工具查清含义再建模,避免误解(如把盲孔做成通孔)。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "description": "要查询的术语,如'盲孔'、'相贯'"}
                    },
                    "required": ["term"]
                }
            }
        }

    def _rollback_to_step(self, seq):
        """恢复到设计日志第 seq 步开始前的模型状态(用户明确说'修正/删除第 N 步')。

        逻辑与 web.py 的 design_log_rollback 一致:
        - 找到第 seq 步之前最近一次成功 model_build 的 manifest 快照并恢复;
        - 遇到 model_clear 则模型为空,忽略更早的 build;
        - seq 之前无 build 则清空模型。
        """
        import re
        log_path = os.path.join(self.project.project_dir, ".design", "log")
        entries = []
        if os.path.exists(log_path):
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            continue
        if seq < 1 or seq > len(entries):
            return {"status": "error", "message": "seq 超出范围 (1..%d)" % len(entries)}
        target_step = None
        for e in entries[:seq]:
            if e.get("action") == "model_clear" or (e.get("action") == "tool_call" and "model_clear" in e.get("instruction", "")):
                target_step = None
                continue
            if e.get("action") == "model_build" and e.get("result_log", {}).get("status") == "ok":
                target_step = e.get("output_dir") or ""
        restored_parts = 0
        if target_step:
            manifest_path = os.path.join(self.project.project_dir, target_step, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
                state = {
                    "parts": manifest.get("parts", []),
                    "joints": manifest.get("joints", []),
                    "created_at": None,
                    "updated_at": None,
                    "schema_version": "1.0",
                    "build_counter": 0,
                }
                cad_dir = os.path.join(self.project.project_dir, "cad")
                if os.path.isdir(cad_dir):
                    state["build_counter"] = len([d for d in os.listdir(cad_dir) if os.path.isdir(os.path.join(cad_dir, d))])
                with open(os.path.join(self.project.project_dir, ".model_state.json"), "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
                restored_parts = len(state["parts"])
                # 重新加载 ModelState 内存态
                self.model_state = ModelState(self.project.project_dir)
        else:
            self.model_state.clear()
        return {
            "status": "ok",
            "seq": seq,
            "total": len(entries),
            "restored_from": target_step or "(起点/空)",
            "restored_parts": restored_parts,
            "message": "已恢复到设计日志第 %d 步开始前的状态,后续指令将基于此状态增量修改。请向用户确认下一步。" % seq,
        }

    def _invalidate_build_cache(self):
        """失效 model_build 防重缓存(model_clear/回滚等"重新设计"语义)。"""
        for _attr in ("_last_build_sig", "_last_build_version", "_last_build_files"):
            if hasattr(self, _attr):
                delattr(self, _attr)

    def _execute_tool(self, tool_name, arguments):
        """工具执行总入口:任何异常转为 error 结果回给 LLM 自纠,
        不让单工具失败打断会话线程(否则 assistant 回复永远缺失)。"""
        try:
            return self._execute_tool_inner(tool_name, arguments)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-500:]
            self.history.append("tool", {
                "tool": tool_name, "args": arguments,
                "error": str(e)[:300], "traceback": tb})
            return json.dumps({
                "error": "工具执行失败: %s" % e,
                "hint": "请根据错误调整参数后重试;若是参数名问题,先查 "
                        "list_design_primitives 的参数定义。",
                "traceback_tail": tb[-200:],
            }, ensure_ascii=False)

    def _execute_tool_inner(self, tool_name, arguments):
        # 来源声明:model_* 工具链 = 合法状态写入来源(审计区分)
        if tool_name.startswith("model_"):
            self.model_state.set_write_source("agent:model_" + tool_name.split("_", 1)[1])
        # === Requirement parsing ===
        if tool_name == "lookup_term":
            # 混合查询: MySQL 精确匹配 + RAGFlow 语义搜索
            term = arguments.get("term", "")
            if self.rag:
                result = self.rag.lookup_term_hybrid(term)
                return json.dumps(result, ensure_ascii=False)
            else:
                from .prompts.mech_terms import lookup_term
                return lookup_term(term)

        # === 国标知识库(B/C) ===
        if tool_name == "query_standard":
            return query_standard(arguments.get("query", ""),
                                  domain=arguments.get("domain", "gbstd"))
        if tool_name == "check_design_compliance":
            return check_design_compliance(arguments.get("features", []))

        if tool_name == "parse_requirement":
            spec = parse_requirement(arguments["text"], user_id=self.user_id)
            self.current_spec = spec
            self.history.append("tool", {"tool": "parse_requirement", "result": spec})
            return json.dumps(spec, ensure_ascii=False)

        # === Primitives ===
        if tool_name == "list_design_primitives":
            # 8103 优先(动态原语即时可见),失败降级本地
            from .primitives_client import list_primitives as list_prims_remote
            prims = list_prims_remote()
            self._primitives_listed = True
            return json.dumps(prims, ensure_ascii=False)

        if tool_name == "design_sentence":
            # 唯一建模入口:LLM 只翻译,计算归 8103 演算器(设计语言演算架构 V0)
            from .primitives_client import resolve_intent
            res = resolve_intent(arguments.get("sentence") or {})
            if res is None:
                return json.dumps({"status": "error",
                                   "message": "演算服务(8103)不可用,请稍后重试"},
                                  ensure_ascii=False)
            if res.get("status") == "invalid":
                # 语法打回:翻译问题,LLM 重新翻译,不是换建模方案
                return json.dumps({"status": "error", "errors": res.get("errors", []),
                                   "message": "句子不合法,已打回。请修正词汇/参数后重新翻译提交"},
                                  ensure_ascii=False)
            if res.get("status") == "violation":
                return json.dumps({"status": "violation", "checks": res.get("checks", []),
                                   "message": "约束判定 VIOLATION——必须原样转述给用户,"
                                              "禁止自行修改设计或换方案重试"},
                                  ensure_ascii=False)
            added = 0
            for p in res.get("parts", []):
                self.model_state.add_part(p["type"], p["params"])
                added += 1
            self.history.append("tool", {"tool": "design_sentence", "parts": added})
            return json.dumps({"status": "ok", "parts_added": added,
                               "trace": res.get("trace", []),
                               "checks": res.get("checks", []),
                               "message": "演算完成,零件已按计算结果登记。"
                                          "请调用 model_build 出图,并向用户回述演算轨迹与判定结果。"},
                              ensure_ascii=False)

        if tool_name == "q_apply":
            # Primordium V0.1: LLM 只交符号 ΔQ, 内核驱动原语(Σ→加法器→Π→Δ→Ω→判定→S)
            if not hasattr(self, "_kernel"):
                self._kernel = Kernel(self.project_dir, model_state=self.model_state)
            res = self._kernel.run_instruction(arguments.get("ops", []),
                                               source=arguments.get("source", ""))
            if res["status"] == "invalid":
                self.history.append("tool", {"tool": "q_apply", "errors": res.get("errors")})
                return json.dumps({"status": "error", "errors": res.get("errors", []),
                                   "message": "ΔQ 校验未过,已打回。按 errors 逐条修正词汇/参数后重新 q_apply,"
                                              "禁止改用其它建模工具。"},
                                  ensure_ascii=False)
            self.history.append("tool", {"tool": "q_apply", "trace": res.get("trace")})
            return json.dumps({"status": "ok", "verdict": res.get("verdict"),
                               "echo": res.get("echo"),
                               "message": "ΔQ 已落账(内核序列 Σ→加法器→Π→Δ→Ω→判定→S)。"
                                          "请调用 model_build 出图,并将 echo 摘要转述给用户确认。"},
                              ensure_ascii=False)

        if tool_name == "structure_search":
            result = handle_structure_search(arguments)
            self.history.append("tool", {"tool": "structure_search", "args": arguments})
            return result

        if tool_name == "model_get_state":
            return json.dumps(self.model_state.get_state(), ensure_ascii=False)

        if tool_name == "model_add_group":
            name = self.model_state.add_group(arguments["name"], arguments.get("parent"))
            self.history.append("tool", {"tool": "model_add_group", "args": arguments})
            return json.dumps({"name": name, "status": "added"})

        if tool_name == "model_add_part":
            if not self._primitives_listed:
                # 硬护栏:未查原语清单禁止建模(防凭记忆猜原语名/硬凑几何)
                self.history.append("tool", {"tool": "model_add_part", "args": arguments,
                                             "blocked": "primitives_not_listed"})
                return json.dumps({
                    "status": "error",
                    "error": "必须先调用 list_design_primitives 查看可用原语清单,"
                             "确认能表达需求的正确原语后再建模。禁止凭记忆假设原语名或硬凑几何。",
                }, ensure_ascii=False)
            name = self.model_state.add_part(arguments["type"], arguments["params"])
            self.history.append("tool", {"tool": "model_add_part", "args": arguments})
            return json.dumps({"name": name, "status": "added"})

        if tool_name == "model_update_part":
            found = self.model_state.update_part(arguments["name"], arguments["updates"])
            self.history.append("tool", {"tool": "model_update_part", "args": arguments})
            if found:
                return json.dumps({"status": "updated", "name": arguments["name"]})
            return json.dumps({"status": "error", "message": "part '{}' not found".format(arguments["name"])})

        if tool_name == "model_remove_part":
            found = self.model_state.remove_part(arguments["name"])
            self.history.append("tool", {"tool": "model_remove_part", "args": arguments})
            return json.dumps({"removed": found})

        if tool_name == "model_add_joint":
            params = arguments.get("params", {})
            name = self.model_state.add_joint(arguments["type"], params)
            self.history.append("tool", {"tool": "model_add_joint", "args": arguments})
            return json.dumps({"name": name, "status": "added"})

        if tool_name == "model_update_joint":
            found = self.model_state.update_joint(arguments["name"], arguments["updates"])
            self.history.append("tool", {"tool": "model_update_joint", "args": arguments})
            if found:
                return json.dumps({"status": "updated", "name": arguments["name"]})
            return json.dumps({"status": "error", "message": "joint '{}' not found".format(arguments["name"])})

        if tool_name == "model_remove_joint":
            found = self.model_state.remove_joint(arguments["name"])
            self.history.append("tool", {"tool": "model_remove_joint", "args": arguments})
            return json.dumps({"removed": found})

        if tool_name == "model_build":
            # 防重护栏:状态未变且已构建成功 → 返回缓存,阻止 LLM 循环重建
            import hashlib as _h
            _sig = _h.sha256(json.dumps(
                {"p": self.model_state.state.get("parts", []),
                 "j": self.model_state.state.get("joints", [])},
                ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
            if getattr(self, "_last_build_sig", None) == _sig:
                # 缓存命中也必须把产物登记进本轮任务,否则本轮 UI 拿不到结果文件
                # (2026-09-01"重新设计看不到结果"事故的修复之二)
                for p in getattr(self, "_last_build_files", []):
                    _abs = p if os.path.isabs(p) else os.path.join(self.project_dir, p)
                    if _abs not in self._current_files:
                        self._current_files.append(_abs)
                _cv = getattr(self, "_last_build_version", None)
                if _cv is not None and _cv not in self._current_versions:
                    self._current_versions.append(_cv)
                return json.dumps({
                    "status": "ok", "cached": True,
                    "version": getattr(self, "_last_build_version"),
                    "files": getattr(self, "_last_build_files", []),
                    "message": "模型自上次成功构建后无任何变化,结果已缓存。"
                               "禁止再次调用 model_build —— 请立即直接回复用户,总结建模结果。",
                }, ensure_ascii=False)
            result = self.model_state.build()
            if result.get("status") == "ok":
                self._last_build_sig = _sig
                self._last_build_version = result.get("version")
                self._last_build_files = _to_rel(result.get("files", []), self.project_dir)
            files = result.get("files", [])
            self._current_files.extend(files)
            v = result.get("version")
            if v is not None:
                self._current_versions.append(v)
            summary = self.model_state.summary()
            # 历史/日志记录相对项目根路径(cad/{step_id}/file),保证历史链接可精确定位当时结果;
            # LLM 响应里仍给绝对路径(便于工具链使用)。
            rel_files = _to_rel(files, self.project_dir)
            history_entry = {"tool": "model_build", "result": {**result, "files": rel_files}}
            if v is not None:
                history_entry["version"] = v
            self.history.append("tool", history_entry)
            response = {"status": result.get("status"), "files": files}
            if v is not None:
                response["version"] = v
            response["summary"] = summary
            # Log to .design/log —— 结构化五要素
            # instruction: 本次设计指示(从最近一条用户消息提取)
            instruction = ""
            for m in reversed(self.messages):
                if m.get("role") == "user":
                    instruction = (m.get("content") or "")[:300]
                    break
            log_entry = {
                "action": "model_build",
                "instruction": instruction,
                "llm_response": getattr(self, "_last_llm_content", "")[:1000],
                "output_dir": os.path.join("cad", result.get("step_dir", "")) if result.get("step_dir") else "",
                "result_log": {
                    "status": result.get("status"),
                    "files": rel_files,
                    "version": v,
                    "step_id": result.get("step_id", ""),
                    "summary": summary,
                    # 失败可观测:message(硬律违规/服务提示)或 stderr(FreeCAD 异常)
                    "message": (result.get("message") or result.get("stderr") or "")[:400],
                    "violations": result.get("violations"),
                },
            }
            self.project.append_log(log_entry)
            return json.dumps(response, ensure_ascii=False)

        if tool_name == "model_save_version":
            result = self.model_state.save_version(arguments.get("label", ""))
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "model_clear":
            self.model_state.clear()
            # 清空=重新设计语义:构建缓存一并失效。
            # 否则"清空→重建相同模型"会误命中防重缓存,跳过真实构建,
            # 导致本轮无新产物、UI 无结果文件(2026-09-01 事故根因)。
            self._invalidate_build_cache()
            self.history.append("tool", {"tool": "model_clear"})
            return json.dumps({"status": "cleared", "parts": 0, "joints": 0})

        if tool_name == "model_list_versions":
            versions = self.model_state.list_versions()
            return json.dumps({"versions": versions}, ensure_ascii=False)

        if tool_name == "model_rollback":
            result = self.model_state.rollback(arguments["version"])
            self.history.append("tool", {"tool": "model_rollback", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "design_log_rollback":
            # 用户明确说"修正/删除第 N 步的修改"时:恢复到该步开始前的模型状态
            seq = int(arguments.get("seq", 0))
            result = self._rollback_to_step(seq)
            self.history.append("tool", {"tool": "design_log_rollback", "args": arguments, "result": result})
            return json.dumps(result, ensure_ascii=False)

        # === Communication tools ===
        if tool_name == "request_tool":
            req_id = request_tool(
                arguments["name"], arguments["description"],
                arguments.get("priority", "P2"),
                arguments.get("params_hint", ""),
                arguments.get("usage_scenario", ""),
            )
            self.history.append("tool", {"tool": "request_tool", "args": arguments})
            return json.dumps({"request_id": req_id, "status": "submitted"})

        if tool_name == "check_tool_status":
            result = check_tool_status(arguments.get("tool_name"))
            self.history.append("tool", {"tool": "check_tool_status", "result": result})
            return json.dumps(result, ensure_ascii=False)

        # === Design Loop(缺口→原语→重做→审阅) ===
        if tool_name == "submit_gap":
            result = submit_gap(
                arguments["name"], arguments["description"],
                arguments.get("priority", "P2"),
                arguments.get("params_hint", ""),
                arguments.get("usage_scenario", ""),
                arguments.get("current_state", ""),
            )
            self.history.append("tool", {"tool": "submit_gap", "args": arguments, "result": result})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "check_loop":
            jid = arguments.get("job_id")
            # 防轮询死循环:同一 job 连续第 3 次查询 → 直接断念(deepseek 高发)
            k = "_poll_" + str(jid)
            n = getattr(self, k, 0) + 1
            setattr(self, k, n)
            if n >= 3:
                out = {"status": "pending",
                       "message": "已连续查询 %d 次仍 pending——后端暂无人响应。"
                                  "禁止再次 check_loop。请立即基于当前能力继续设计并直接回复用户;"
                                  "缺口稍后由人工处理后端处理(你已提交过 gap 的无需等)。" % n}
                self.history.append("tool", {"tool": "check_loop", "result": out})
                return json.dumps(out, ensure_ascii=False)
            result = check_loop(jid)
            # 结果附行为指令:pending 不许连发
            try:
                r = json.loads(json.dumps(result)) if isinstance(result, str) else result
            except Exception:
                r = result
            if isinstance(r, dict) and r.get("status") in ("pending_gap", "pending", "not_found", "empty"):
                r["hint"] = "仍等待后端。禁止连续调用 check_loop——请立即继续当前设计或直接回复用户。"
                result = r
            self.history.append("tool", {"tool": "check_loop", "result": result})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "submit_result":
            result = submit_result(
                arguments["job_id"], arguments["summary"],
                files=self._current_files,
                state_summary=arguments.get("state_summary", ""),
            )
            self.history.append("tool", {"tool": "submit_result", "args": arguments, "result": result})
            return json.dumps(result, ensure_ascii=False)

        # === Memory tools ===
        if tool_name == "save_memory":
            key = mem_save(arguments["key"], arguments["content"])
            return json.dumps({"key": key, "status": "saved"})

        if tool_name == "recall_memory":
            result = mem_recall(arguments.get("key"))
            return json.dumps({"content": result}, ensure_ascii=False)

        if tool_name == "list_memories":
            keys = mem_list_keys()
            return json.dumps({"keys": keys})

        # === Digital Twin tools ===
        if tool_name == "dtwin_solve":
            from .dtwin_client import kinematics_solve
            parts = arguments.get("parts", [])
            joints = arguments.get("joints", [])
            params = arguments.get("parameters", {})
            result = kinematics_solve(parts, joints, params)
            self.history.append("tool", {"tool": "dtwin_solve", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        # === Material library tools (mn-material 5 tables) ===
        if tool_name in MATERIAL_TOOL_IMPL:
            fn = MATERIAL_TOOL_IMPL[tool_name]
            result = fn(arguments or {})
            self.history.append("tool", {"tool": tool_name, "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "dtwin_animate":
            from .dtwin_client import kinematics_animate
            result = kinematics_animate(
                arguments.get("parts", []),
                arguments.get("joints", []),
                arguments.get("angle_start", 0),
                arguments.get("angle_end", 45),
                arguments.get("steps", 10),
            )
            self.history.append("tool", {"tool": "dtwin_animate", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "dtwin_bellows":
            from .dtwin_client import simulate_bellows
            result = simulate_bellows(
                arguments["hinge_pos"],
                arguments["attach_a"],
                arguments["attach_b"],
                arguments["initial_length"],
                arguments["angle_deg"],
                arguments.get("axis_dir", "y"),
            )
            self.history.append("tool", {"tool": "dtwin_bellows", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "dtwin_validate":
            from .dtwin_client import validate_configuration
            result = validate_configuration(
                arguments.get("parts", []),
                arguments.get("joints", []),
                arguments.get("parameters", {}),
                arguments.get("bounds", {}),
            )
            self.history.append("tool", {"tool": "dtwin_validate", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "workshop_open":
            result = self.workshop_mgr.open(
                arguments["topic"],
                arguments.get("description", ""))
            self.history.append("tool", {"tool": "workshop_open"})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "workshop_contribute":
            result = self.workshop_mgr.contribute(
                arguments["session_id"], arguments["author"],
                arguments["content"], arguments.get("category"))
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "workshop_synthesize":
            result = self.workshop_mgr.synthesize(arguments["session_id"])
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "design_submit_review":
            result = self.review_mgr.submit(arguments.get("label", ""))
            self.history.append("tool", {"tool": "design_submit_review"})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "design_list_reviews":
            result = self.review_mgr.list()
            return json.dumps({"reviews": result}, ensure_ascii=False)

        if tool_name == "design_get_review":
            result = self.review_mgr.get(arguments.get("review_id"))
            if result:
                return json.dumps(result, ensure_ascii=False)
            return json.dumps({"error": "not found"})

        if tool_name == "design_respond_item":
            result = self.review_mgr.respond_to_item(
                arguments["review_id"], arguments["item_id"],
                arguments["response"], arguments.get("accept", True))
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "select_design_template":
            result = match_template(arguments.get("requirement", ""))
            if result:
                content = result["content"]
                self.messages[0]["content"] += "\n\n## 设计模版\n" + content
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "list_design_templates":
            return json.dumps(list_templates(), ensure_ascii=False)

        if tool_name == "robot_list_models":
            from .robot_tools import robotics
            return json.dumps(robotics.list_robot_models(), ensure_ascii=False)

        if tool_name == "robot_dh_forward":
            from .robot_tools import _get_dh, robotics
            dh = _get_dh(arguments.get("model"), arguments.get("dh_params"))
            result = robotics.forward_kinematics(dh, arguments["joint_angles_deg"])
            self.history.append("tool", {"tool": "robot_dh_forward", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "robot_workspace":
            from .robot_tools import _get_dh, _get_ranges, robotics
            dh = _get_dh(arguments.get("model"), arguments.get("dh_params"))
            ranges = _get_ranges(arguments.get("model"), arguments.get("joint_ranges_deg"))
            result = robotics.workspace_scan(dh, ranges)
            self.history.append("tool", {"tool": "robot_workspace", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "dtwin_validate_range":
            from .dtwin_client import validate_range
            result = validate_range(
                arguments.get("parts", []),
                arguments.get("joints", []),
                arguments.get("bounds", {}),
                arguments.get("angle_start", 0),
                arguments.get("angle_end", 90),
                arguments.get("step", 5),
            )
            self.history.append("tool", {"tool": "dtwin_validate_range", "args": arguments})
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "calc_drive_torque":
            from .dtwin_client import calc_drive_torque
            result = calc_drive_torque(
                arguments["load_N"], arguments["lever_mm"],
                arguments.get("angle_deg", 0))
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "calc_actuator_force":
            from .dtwin_client import calc_actuator_force
            result = calc_actuator_force(
                arguments["torque_Nm"], arguments["mount_offset_mm"],
                arguments.get("mount_angle_deg", 90))
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "suggest_actuator":
            from .dtwin_client import suggest_actuator
            result = suggest_actuator(
                arguments["force_N"], arguments["stroke_mm"],
                arguments.get("speed_mm_s", 10))
            return json.dumps(result, ensure_ascii=False)

        # === Spatial computation ===
        if tool_name == "calc_hinge_rotation":
            result = spatial_tools.hinge_rotation(
                tuple(arguments["hinge_pos"]),
                arguments["axis_dir"],
                arguments["angle_deg"],
                tuple(arguments["point"]),
            )
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "calc_bellows_compression":
            result = spatial_tools.bellows_compression(
                arguments["initial_length"],
                arguments["angle_deg"],
                tuple(arguments["hinge_pos"]),
                tuple(arguments["attach_a"]),
                tuple(arguments["attach_b"]),
                arguments.get("axis_dir", "y"),
            )
            return json.dumps(result, ensure_ascii=False)


        if tool_name == "calc_cantilever_bending":
            result = spatial_tools.cantilever_bending(
                arguments["force_N"],
                arguments["length_mm"],
                arguments["width_mm"],
                arguments["height_mm"],
                arguments.get("E_MPa", 70000),
            )
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "calc_pin_shear":
            result = spatial_tools.hinge_pin_shear(
                arguments["load_N"],
                arguments["pin_r"],
                arguments.get("pin_count", 2),
                arguments.get("material", "steel_304"),
            )
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "suggest_ergonomic_dimensions":
            result = spatial_tools.resolve_ergonomic_dimensions(
                arguments.get("body_height_mm", 1700),
                arguments.get("body_weight_kg", 75),
            )
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "estimate_sitting_loads":
            result = spatial_tools.estimate_seated_loads(
                arguments.get("body_weight_kg", 75),
                arguments.get("thigh_ratio", 0.3),
            )
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "check_part_interference":
            result = spatial_tools.check_interference(arguments.get("parts", []))
            return json.dumps(result, ensure_ascii=False)

        # === Legacy tools ===
        if tool_name == "freecad_execute":
            result = self.freecad.execute_python(arguments["code"])
            self.history.append("tool", {"tool": "freecad", "args": arguments, "result": result})
            files = result.get("files", [])
            self._current_files.extend(files)
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "save_document":
            path = self.docs.save_design_note(arguments["title"], arguments["content"], arguments.get("section", "notes"))
            self.history.append("tool", {"tool": "document", "path": path})
            return "Document saved: " + path

        if tool_name == "record_decision":
            path = self.docs.save_decision(arguments["question"], arguments.get("options", []), arguments["decision"], arguments["reason"], arguments.get("impact", ""))
            self.history.append("decision", arguments)
            return "Decision recorded: " + path

        if tool_name == "record_change":
            path = self.docs.save_changelog(arguments["change"], arguments.get("reason", ""))
            self.history.append("change", arguments)
            return "Change recorded: " + path

        if tool_name == "record_calculation":
            path = self.docs.save_calculation(arguments["title"], arguments.get("formula", ""), arguments.get("inputs", {}), arguments["result"], arguments.get("notes", ""))
            self.history.append("calculation", arguments)
            return "Calculation recorded: " + path

        if tool_name == "rag_search":
            result = self.rag.search(
                arguments.get("question", ""),
                top_k=arguments.get("top_k", 5),
            )
            self.history.append("tool", {"tool": "rag_search", "args": arguments})
            if isinstance(result, list):
                texts = ["[%d] %s" % (i+1, r["content"][:500]) for i, r in enumerate(result[:5])]
                return "\n\n".join(texts)
            return json.dumps(result, ensure_ascii=False)

        if tool_name == "rag_list_datasets":
            result = self.rag.list_datasets()
            if isinstance(result, list):
                lines = ["Available knowledge bases:"] + ["- %s (%d chunks)" % (d["name"], d["chunk_count"]) for d in result]
                return "\n".join(lines)
            return json.dumps(result, ensure_ascii=False)

        return "Unknown tool: " + tool_name

    # ================= 上下文管理(A1/A2) =================

    def _restore_history(self):
        """agent 重建时从 DesignHistory 恢复对话上下文。

        组成:模型摘要(事实源) + 最近 K 轮用户/助手对话 + 更早的决策摘要提示。
        工具调用细节不恢复——结果已体现在 model_state/决策记录里。
        """
        try:
            entries = self.history.get_all()
        except Exception:
            return
        turns = []
        for e in entries:
            if e.get("type") == "user":
                turns.append(("user", (e.get("data") or {}).get("content", "")))
            elif e.get("type") == "assistant":
                c = (e.get("data") or {}).get("content", "")
                if c:
                    turns.append(("assistant", c))
        if not turns:
            return
        recent = turns[-self._RECENT_TURNS:]
        older = len(turns) - len(recent)
        block = []
        if older > 0:
            block.append(
                "## 历史会话说明\n"
                "本会话此前已有 %d 轮对话(共 %d 条消息)。更早的设计决策/计算"
                "已通过 record_decision/record_calculation 记录,必要时用工具查阅;"
                "模型当前状态以「当前模型」摘要为准。\n" % (older, len(turns)))
        block.append("## 最近对话(连续性参考)")
        for role, content in recent:
            text = content if len(content) <= 800 else content[:600] + "\n...(已截断)"
            block.append("[%s] %s" % ("用户" if role == "user" else "助手", text))
        self.messages[0]["content"] += "\n\n" + "\n\n".join(block) + "\n"

    def _compact_context(self):
        """轮末收敛:老对话轮次替换为一句摘要,保留最近 K 轮。

        messages 结构保持 [system, ...对话/工具消息] 合法序列——
        只删除(压缩)中段的 user/assistant/tool 组,并插入一条摘要
        user/assistant 对,避免破坏 tool_call_id 配对。
        """
        try:
            msgs = self.messages
            if len(msgs) <= 2 + self._RECENT_TURNS * 4:
                return
            # 找出所有顶层 user 消息的索引(system=0 之后)
            user_idx = [i for i, m in enumerate(msgs)
                        if i > 0 and m.get("role") == "user"]
            if len(user_idx) <= self._RECENT_TURNS:
                return
            # 保留最近 K 轮的起点;之前的压成一条摘要
            keep_from = user_idx[-self._RECENT_TURNS]
            head = msgs[:1]  # system
            compacted = msgs[1:keep_from]
            rest = msgs[keep_from:]
            n_rounds = len(user_idx) - self._RECENT_TURNS
            summary = (
                "系统提示:此前 %d 轮对话已压缩。设计过程中的关键决策与计算"
                "已通过 record_decision/record_calculation 落盘(可用 changelog/"
                "文档工具查阅);模型当前状态以 system 中的「当前模型」摘要为准,"
                "修改前可 model_get_state 确认。" % n_rounds)
            self.messages = head + [
                {"role": "user", "content": summary},
                {"role": "assistant", "content": "已了解,基于当前模型状态继续。"},
            ] + rest
        except Exception:
            pass  # 压缩失败不影响主流程

    def _repair_tool_pairing(self):
        """修复 tool_calls/tool 配对(SSE 中断等导致的中间态)。

        场景:chat_stream 在工具执行中连接断开,messages 停在
        assistant(tool_calls) 已入、tool 结果未入的状态;下一条 user
        直接跟随时 API 报 400(insufficient tool messages)。
        策略:对每个带 tool_calls 的 assistant 消息,检查其后是否缺少
        对应 tool 响应——缺的补 "(中断,结果未返回)" 占位,保证序列合法。
        """
        try:
            msgs = self.messages
            for i, m in enumerate(msgs):
                calls = m.get("tool_calls") or []
                if m.get("role") != "assistant" or not calls:
                    continue
                # 找该 assistant 之后、下一条 user/assistant(tool_calls) 之前的 tool 响应
                responded = set()
                for j in range(i + 1, len(msgs)):
                    n = msgs[j]
                    if n.get("role") == "tool":
                        responded.add(n.get("tool_call_id"))
                    elif n.get("role") == "user":
                        break
                missing = [tc["id"] for tc in calls
                           if tc["id"] not in responded]
                if not missing:
                    continue
                # 在该 assistant 消息后插入占位 tool 响应
                insert_at = i + 1
                for k, mid in enumerate(missing):
                    msgs.insert(insert_at + k, {
                        "role": "tool", "tool_call_id": mid,
                        "content": "(执行中断,结果未返回;如需该结果请重新调用工具)",
                    })
        except Exception:
            pass

    def _truncate_tool_result(self, result: str) -> str:
        """工具结果截断:超长留头尾,提示已存盘可再查。"""
        if not isinstance(result, str) or len(result) <= self._TOOL_RESULT_MAX:
            return result
        head = result[:1500]
        tail = result[-300:]
        return (head + "\n...(中间内容省略,完整结果已存盘;"
                "如需细节请用更精确的查询参数重新检索)\n" + tail)

    def chat(self, user_input, stream=False):
        self.messages.append({"role": "user", "content": user_input})
        self.history.append("user", {"content": user_input})
        self._current_files = []
        self._current_versions = []
        max_iterations = self.project.get_config().get("max_iterations", 50)
        for _ in range(max_iterations):
            self._repair_tool_pairing()
            response = chat(self.messages, tools=self.tools, stream=stream, user_id=self.user_id)
            message = response.choices[0].message
            if not message.tool_calls:
                content = message.content or ""
                self.messages.append({"role": "assistant", "content": content})
                entry = {"content": content, "files": _to_rel(self._current_files, self.project_dir)}
                if self._current_versions:
                    entry["build_versions"] = self._current_versions
                self.history.append("assistant", entry)
                result = {"text": content, "files": self._current_files}
                self._compact_context()
                return json.dumps(result, ensure_ascii=False)
            if message.content:
                yield json.dumps({"type": "progress", "content": "推理: " + message.content[:200]}) + "\n"
            self.messages.append({
                "role": "assistant", "content": message.content,
                "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in message.tool_calls]
            })
            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self._truncate_tool_result(self._execute_tool(tc.function.name, args))
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        return json.dumps({"text": "达到最大迭代次数，请简化需求或分步提问。", "files": self._current_files}, ensure_ascii=False)

    def chat_stream(self, user_input):
        '''Generator version of chat(). Yields progress during tool execution.'''
        self.messages.append({"role": "user", "content": user_input})
        self.history.append("user", {"content": user_input})
        self._current_files = []
        self._current_versions = []
        self._last_llm_content = ""  # 最近一次 LLM 回应(推理/工具调用前内容)

        # Log user message to .design/log —— 设计指示
        self.project.append_log({
            "action": "user_message",
            "instruction": user_input[:500],
        })

        max_iterations = self.project.get_config().get("max_iterations", 50)
        consecutive_llm_errors = 0
        max_consecutive_errors = 3
        stop_reason = None  # 提前停止原因(写 history,前端可恢复)
        for i in range(max_iterations):
            yield json.dumps({"type": "progress", "content": "思考中...（第%d轮）" % (i + 1)}) + "\n"
            try:
                from .llm import chat as _chat_fn
                self._repair_tool_pairing()
                response = _chat_fn(self.messages, tools=self.tools, user_id=self.user_id)
            except Exception as _llm_err:
                from .llm import _friendly_error, _is_fatal_api_error
                from openai import APIStatusError
                err_msg = _friendly_error(_llm_err)
                is_fatal = isinstance(_llm_err, APIStatusError) and _is_fatal_api_error(_llm_err)
                consecutive_llm_errors += 1
                if is_fatal:
                    stop_reason = "\n\n" + err_msg + "\n\n已停止，请解决上述问题后重试。"
                    yield json.dumps({"type": "token", "content": stop_reason}) + "\n"
                    break
                elif consecutive_llm_errors >= max_consecutive_errors:
                    stop_reason = "\n\n" + err_msg + "\n\n连续 %d 次 API 错误，已停止。请检查网络或 API 配置。" % max_consecutive_errors
                    yield json.dumps({"type": "token", "content": stop_reason}) + "\n"
                    break
                else:
                    yield json.dumps({"type": "progress", "content": err_msg + " (第%d/%d次重试)" % (consecutive_llm_errors, max_consecutive_errors)}) + "\n"
                    import time
                    time.sleep(min(2 ** consecutive_llm_errors, 15))
                    continue
            consecutive_llm_errors = 0
            message = response.choices[0].message
            llm_content = message.content or ""
            self._last_llm_content = llm_content  # 供 model_build 等日志引用 LLM 回应
            if not message.tool_calls:
                content = llm_content
                self.messages.append({"role": "assistant", "content": content})
                entry = {"content": content, "files": _to_rel(self._current_files, self.project_dir)}
                if self._current_versions:
                    entry["build_versions"] = self._current_versions
                self.history.append("assistant", entry)
                # Log assistant response to .design/log —— LLM 完整回应
                log_entry = {
                    "action": "assistant_response",
                    "instruction": "",
                    "llm_response": content,
                    "result_log": {
                        "files": _to_rel(self._current_files, self.project_dir),
                        "build_versions": self._current_versions or [],
                    },
                }
                self.project.append_log(log_entry)
                yield json.dumps({"type": "token", "content": content}) + "\n"
                for f in self._current_files:
                    yield json.dumps({"type": "file", "content": f}) + "\n"
                self._compact_context()
                return
            if message.content:
                yield json.dumps({"type": "progress", "content": "推理: " + message.content[:200]}) + "\n"
            self.messages.append({
                "role": "assistant", "content": message.content,
                "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in message.tool_calls]
            })
            for tc in message.tool_calls:
                tname = tc.function.name
                args = json.loads(tc.function.arguments)
                keys_str = str(list(args.keys()))[:60]
                yield json.dumps({"type": "step", "content": "执行: %s %s" % (tname, keys_str)}) + "\n"
                result = self._truncate_tool_result(self._execute_tool(tname, args))
                # 结构化工具调用日志:instruction=设计指示(工具+参数), llm_response=LLM 回应(调用该工具前的推理), result_log=结果摘要
                self.project.append_log({
                    "action": "tool_call",
                    "instruction": "%s %s" % (tname, json.dumps(args, ensure_ascii=False)[:200]),
                    "llm_response": llm_content,
                    "result_log": {
                        "tool": tname,
                        "params": {k: (str(v)[:200] if not isinstance(v, (int, float, bool, type(None))) else v) for k, v in args.items()},
                        "result": str(result)[:500],
                    },
                })
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        # Always scan for generated files, even on early exit
        if self._current_files:
            for f in self._current_files:
                yield json.dumps({"type": "file", "content": f}) + "\n"

        # 提前停止(LLM 错误/迭代耗尽)时,把停止原因写入 history——否则前端刷新后看不到任何结果
        if stop_reason:
            self.messages.append({"role": "assistant", "content": stop_reason})
            self.history.append("assistant", {"content": stop_reason, "files": _to_rel(self._current_files, self.project_dir)})
            self.project.append_log({
                "action": "assistant_response",
                "instruction": "",
                "llm_response": stop_reason,
                "result_log": {"files": _to_rel(self._current_files, self.project_dir), "build_versions": self._current_versions or []},
            })

        # 监护者:会话结束,分析设计日志,记录错误模式与修正建议(自我进化)
        try:
            from .guardian import record_guardian
            record_guardian(self.project.project_dir, self.project.get_project_id())
        except Exception:
            pass

    def get_status(self):
        from datetime import datetime
        config = self.project.get_config()
        proj_name = config.get("name", "未命名")
        proj_phase = config.get("phase", "concept")
        user_count = len([m for m in self.messages if m.get("role") == "user"])
        status = "项目: " + proj_name + "\n"
        status += "阶段: " + proj_phase + "\n"
        status += "对话轮数: %d" % user_count + "\n"
        status += "设计历史: %d 条" % len(self.history.get_all()) + "\n"
        status += "\n" + self.history.get_summary()
        return status


from datetime import datetime
