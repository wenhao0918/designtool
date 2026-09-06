"""LLM 译码员 — 自然语言 → 纯数字串

规则（Spec_V1）：
- LLM 只输出一串数字（逗号或空格分隔），禁止输出 JSON/括号/标签/解释
- 无法映射的词输出 9999 报警
- 数字串由内核盲扫描执行

三级 fallback（2026-09-03 对齐）：
  1. 译码表主词精确命中 → 直译
  2. mech_terms 别名匹配 → 归一后直译（"圆球"→"球"）
  3. RAGFlow 向量库语义检索 → 复合词/未收录词拆解上下文（"空心球"→球+减）

Prompt：注入译码表 + 三级上下文 + 规则 + 用户指令 + 历史对象指称
"""
import re
from anvil.encoder.codetable import prompt_text, direct_hits, CODETABLE

# 算子码集(校验用:参数位遇码=错位标志)
_VOPSET = {c for c in CODETABLE if c >= 100}
from anvil.llm import chat


def resolve_context(text):
    """译码前三级查询，结果作 LLM 译码上下文（层间独立，均容忍失败）"""
    ctx = {"direct": direct_hits(text), "alias": [], "rag": []}

    # 第2级：mech_terms 别名匹配（term 主词 + aliases 逗号分隔别名）
    try:
        from anvil.prompts.mech_terms import get_all_terms
        alias_hits = []
        for t in get_all_terms():
            if t.get("term") in text:
                alias_hits.append(t["term"])
                continue
            for a in (t.get("aliases") or "").split(","):
                a = a.strip()
                if a and a in text:
                    alias_hits.append("%s→%s" % (a, t["term"]))
                    break
        ctx["alias"] = alias_hits[:10]
    except Exception:
        pass

    # 第3级：RAGFlow 向量库语义检索（复合词/未收录词兜底；后端可能忽略 top_k，强制截 3 条）
    try:
        from anvil.rag import get_backend
        results = get_backend().search(text, top_k=3) or []
        ctx["rag"] = [r.get("content", "")[:200] for r in results[:3]
                      if isinstance(r, dict) and r.get("content")]
    except Exception:
        pass
    return ctx


def _context_text(ctx):
    """三级上下文 → prompt 注入文本（空层不输出）"""
    lines = []
    if ctx.get("direct"):
        lines.append("直接命中主词：%s" % "、".join(ctx["direct"]))
    if ctx.get("alias"):
        lines.append("别名归一：%s" % "、".join(ctx["alias"]))
    if ctx.get("rag"):
        lines.append("知识库参考（复合词拆解用）：")
        for i, r in enumerate(ctx["rag"], 1):
            lines.append("  %d. %s" % (i, r))
    return "\n".join(lines)


SYSTEM_PROMPT = """你是译码员。判断用户输入并产出双通道输出：数字矩阵（ΔQ 增量）与备注回应。

输出格式（严格遵守）：
第一行 = 数字矩阵，逗号分隔（如 4,50.0,0,0,0）；无新增设计内容时输出 []
第二行起 = 备注/回应文本（对设计的简短说明，或纯对话时的直接回答）

铁律（违反则失败）：
1. 第一行必须是数字矩阵或 []（禁止任何前言/解释），只含数字与逗号（禁止 JSON、括号、单位 mm/度）
2. 矩阵与备注不可同时为空：纯设计指令可不写备注；纯对话/提问/超纲请求矩阵=[]且必须给文字回应
3. **几何体参数表**：每个几何体有固定参数列表=尺寸+位置(体心x,y,z绝对坐标)+方位(倾角,转角)——涉及几何体时先调工具 get_geometry_schema 查参数表，矩阵中编号后按参数表顺序**写满全部参数**，缺项会造成解码错位。可整体省略的算子项省略时不得只写码不带参。**位置算不准就写 -1**（禁止臆造数值/瞎猜坐标）：-1=未定，由内核拓扑心象求解——体元位置位写 -1 后**必须**跟约束算子 759（贴边放置：`759,990,目标序号,侧码,间隙`，侧码 1=X+ 2=X- 3=Y+ 4=Y-）或 752（XY中心对齐，引用目标）；z 写 -1 = 贴地（内核自动）。例如"放在底板右侧距右边缘10毫米"（圆柱r20）→ `2,20.0,20.0,-1,30,-1,0,0,759,990,1,1,10`（x,y 未知位 -1+759 约束，y 若对齐可写 -1,752,990,1 或直接给值）
4. 引用已有对象用 990,序号——序号必须从「已有对象指称索引」按名称/原指令匹配选取，禁止默认用 #1 或凭空猜测；备注中被引用对象写成「名称(#序号)」格式（如 底板(#1)）
5. 本指令内创建的体：991=最新创建，992=次新（如空心球=外球992−内球991）
6. 组合几何体不查表，用基本码组合表达（表=字母表，组合体=单词）；**重复特征=重复段**：同一指令多个相同特征（多孔/多凸台）直接重复写算子段，每段自带定位
7. 指令含设计意图但有词无法映射 → 矩阵含 9999，并在备注里说明缺什么
8. 位置已是几何体参数位（体心绝对坐标）——能按已有尺寸推算出绝对坐标时**直接写进参数位**，不用 750~757 相对定位算子；756 仅用于 207 孔心定位段；750~755 保留给无法推算的相对定位场景
9. **只译当前指令的增量**：历史指令已经执行过，禁止把"已有对象"里的内容重新译一遍；需要基于历史对象操作时只用 990,序号 引用
10. **"重新设计"清零**：用户说"重新设计/从头开始/清空/重置"→ 矩阵含 9998（可单独一条）。9998 表示清空之前所有设计
11. **"重新执行"重做**：用户说"重新执行/重做/再来一次"（指撤销上一步再执行）→ 矩阵仅 `9997`。9997 = 撤销上一条 ΔQ 并用原矩阵重放
12. **融合与独立放置**（执行约束：独立体不得与已有对象重叠）：
   - "添加到…上/组合/合并/凸台/连成一体"类（要成为一体）→ 体元全参数后追加 `100,990,N`（N=目标序号，融合语义下重叠合法）
   - "旁边/另放/附近/一侧"类独立放置 → 新体必须与已有对象**无重叠**，位置须由指令明确给出或唯一推算出
13. **欠约束提问（硬规则，禁止拍脑臆造约束）**：放置类指令含模糊位置词（旁边/附近/一侧/挨着/周围/靠近等）或模糊连接关系（连接/装到…上 未说明融合一体还是分开），而指令中**没有**明确数值（距离/间隙/坐标毫米数）或明确定位关系（如"贴XX面"/"距XX边N毫米"/"中心对齐"）→ **必须**输出矩阵 `[]`，备注以「【欠约束】」开头逐项提问（如"【欠约束】① 放哪一侧？② 距边缘多少毫米？③ 连成一体还是分开？"）。**禁止**自行选取任何默认距离/方向蒙混执行——宁可问，不可猜；补充对话会带上下文，答过的不重复问

算子表（编号→主词，参数紧跟编号后）：
%s

示例：
- "做个球直径100" → 第一行 `4,50.0,0,0,0`（球参数表=半径,球心x,y,z）
- "做个长100宽60高10的底板放在原点角上" → 第一行 `1,100,60,10,50,30,5,0,0`（体心=各向半尺寸→占 x[0,100] y[0,60] z[0,10] 贴地）
- "圆锥底半径15高40，底面在z=0" → 第一行 `3,15.0,0,40.0,0,0,20.0,0,0`（**顶半径=0 才是尖锥**；体心z=高/2）
- "空心球直径100壁厚10" → 第一行 `4,50.0,0,0,0,4,40.0,0,0,0,101,992,991`，备注可为"内球直径=100−2×10"
- "在底板(#1,100×60×10,体心50,30,5)上加个圆柱凸台直径10高20" → 第一行 `2,5.0,20.0,50,30,20.0,0,0`（体心z=板顶10+凸台半高10=20,直接落位）
- "圆柱放在底板(#1,占x[0,100] y[0,60])右侧，圆柱面距右边缘10毫米"（圆柱r20,h20）→ 第一行 `2,20.0,20.0,-1,-1,-1,0,0,759,990,1,1,10,752,990,1`（x/y 由内核按约束求解——759=X+侧间隙10、752=XY中心对齐；z=-1 贴地。**坐标算术全部交给内核,你只写约束**）
- "做一个直径60高12的圆盘底座，中心打一个直径10的贯穿孔" → 第一行 `2,30.0,12.0,0,0,6.0,0,0,207,991,5.0,756,0,0,0`（**新建体+对其打孔的组合**：先体元全参数，再 207 段=`207,991(引用本指令新建的体),半径,756孔心`——207 后第一个必须是引用 990,N 或 991，禁止裸数值开头）
- "你好" → 第一行 `[]`，第二行"你好！有什么想设计的吗？"
- "帮我查个标准件" → 第一行 `[]`，第二行如实说明该查询暂由对话回应、可继续下设计指令
"""


def _parse_matrix_line(line):
    """单行矩阵解析：`[]`→[]；否则提取该行内全部数字（含小数）"""
    if line.strip() in ("[]", "［］", "无", "-"):
        return []
    nums = re.findall(r"-?\d+\.?\d*", line)
    result = []
    for s in nums:
        try:
            v = float(s)
            result.append(int(v) if v.is_integer() else v)
        except Exception:
            continue
    return result


def validate_dltq(dltq, text="", alive_seqs=None):
    """译码正确性校验(确定性,内核裁决,2026-09-06 用户定:译码→检查→重译)。

    结构层:按参数表定长校验——体元参数缺失、207 段结构非法、参数非正。
    引用层:990,N 的 N 必须在 alive_seqs(已有对象)——错引触发重译而非终败。
    覆盖层(宽松):指令中的显著数值应至少一个出现在矩阵(含÷2直径换算),
    全不匹配疑漏译。返回问题列表([]=通过)。
    """
    from anvil.encoder.codetable import geo_arity, GEOMETRY_SCHEMA, get
    issues = []
    i, n = 0, len(dltq)
    while i < n:
        c = int(dltq[i])
        if c in (1, 2, 3, 4, 5, 7, 8) and c in GEOMETRY_SCHEMA:
            need = geo_arity(c)
            if n - (i + 1) < need:
                issues.append("体元%d(%s)参数缺失:需%d个,矩阵只剩%d个"
                              % (c, GEOMETRY_SCHEMA[c]["term"], need, n - (i + 1)))
                break
            vals = dltq[i + 1:i + 1 + need]
            ns = len(GEOMETRY_SCHEMA[c]["size"])
            for k, v in enumerate(vals[:ns]):
                if float(v) == -1:
                    issues.append("体元%d 尺寸参数(%s)=-1 未定——尺寸必须明确;只有位置参数可 -1 并配 759/752 约束由内核求解"
                                  % (c, GEOMETRY_SCHEMA[c]["size"][k]))
                elif float(v) <= 0:
                    issues.append("体元%d 第%d个尺寸参数(%s)=%s 非正数"
                                  % (c, k + 1, GEOMETRY_SCHEMA[c]["size"][k], v))
            # 错位精准定位:参数位(尤其尾部方位位)遇算子码=该体元少参——
            # 定长吞参会吃掉后续算子造成连锁错位(表象在下游,根因在此)
            for k in range(ns, need):
                if int(vals[k]) in _VOPSET:
                    issues.append("体元%d(%s)第%d个参数位遇到算子码%d——该体元参数没写满"
                                  "(共需%d个:尺寸%d+位置3+方位%d),把缺的参数用0补齐后重排矩阵"
                                  % (c, GEOMETRY_SCHEMA[c]["term"], k + 1, int(vals[k]),
                                     need, ns, need - ns - 3))
                    break
            i += 1 + need
        elif c == 207:
            # 段式:引用(0..n) + 半径(首数值) + 可选深度 + 可选756(x,y,z)
            i += 1
            saw_r = False
            while i < n:
                c2 = int(dltq[i])
                if c2 == 990:
                    if i + 1 < n and alive_seqs is not None and int(dltq[i + 1]) not in alive_seqs:
                        issues.append("打孔引用了不存在的对象 #%d——只能引用指称索引中的对象" % int(dltq[i + 1]))
                    i += 2
                elif c2 in (991, 992):
                    i += 1
                elif c2 == 756:
                    if n - i < 4:
                        issues.append("打孔段 756 定位参数不足(需 x,y,z)")
                        i = n
                    else:
                        i += 4
                elif c2 in (750, 751, 752):
                    i += 1
                elif not saw_r:
                    if float(dltq[i]) <= 0:
                        issues.append("打孔半径=%s 非正数" % dltq[i])
                    saw_r = True
                    i += 1
                elif float(dltq[i]) > 0:
                    i += 1  # 深度位
                else:
                    break  # 0=段尾占位,容忍(编译器同样跳过;LLM 习惯性补位不算错)
            if not saw_r:
                issues.append("打孔段缺半径参数")
        elif c == 990:
            if i + 1 >= n:
                issues.append("引用算子 990 缺序号参数")
            elif alive_seqs is not None and int(dltq[i + 1]) not in alive_seqs:
                issues.append("引用了不存在的对象 #%d（已撤销/清零/未创建）——"
                              "只能引用指称索引中的对象;本指令新建的体用 991(最新)/992(次新)" % int(dltq[i + 1]))
            i += 2
        else:
            e = get(c)
            if e is None and c >= 100:
                issues.append("矩阵含未定义/多余算子码 %d——只输出本指令需要的算子,"
                              "写完即止(2026-09-07 尾部游离码检查)" % c)
                i += 1
                continue
            ps = (e.get("params") or []) if e else []
            i += 1
            for pn in ps:
                if i >= n:
                    if not pn.startswith("["):
                        issues.append("算子%d(%s)参数不足:缺%s" % (c, e["term"], pn))
                    break
                if any(k in pn for k in ("引用", "对象", "目标", "面", "轴", "轮廓", "方向")):
                    if int(dltq[i]) == 990:
                        if alive_seqs is not None and i + 1 < n and int(dltq[i + 1]) not in alive_seqs:
                            issues.append("算子%d(%s)引用了不存在的对象 #%d" % (c, e["term"], int(dltq[i + 1])))
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
    # 覆盖层:指令显著数值 vs 矩阵数值(含直径↔半径 ÷2/×2 换算)
    # 过半命中:单值须命中;多值指令至少过半落点,防换算侥幸漏译
    if dltq and text:
        sig = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text) if float(x) >= 3]
        mv = set()
        for v in dltq:
            try:
                f = float(v)
                mv.update((f, f * 2, f / 2))
            except (TypeError, ValueError):
                continue
        import math as _math
        hits = sum(1 for s in sig if s in mv)
        need_hits = max(1, _math.ceil(len(sig) / 2)) if sig else 0
        if sig and hits < need_hits:
            issues.append("指令中的数值(%s)大多未出现在矩阵参数中(命中%d/%d),疑漏译关键尺寸"
                          % (",".join(str(int(s)) if s.is_integer() else str(s) for s in sig[:6]),
                             hits, len(sig)))
    return issues


def _parse_dual(text):
    """双通道解析：矩阵行（可多行连续，拼成一条）+ 备注文本。

    容错：LLM 偶发 markdown 包裹/前言（工具模式下格式漂移,先解释后矩阵）——
    首行无数字且非 [] 标记时,扫描各行找「行首即数字/[] 的矩阵行」提取,
    其余行(含前言)合并为备注；无矩阵行 → 整体视为备注(矩阵空)。

    多行矩阵拼接(2026-09-07)：多孔 207 段 LLM 常按行分写（每行一段）而非
    单行连写——从起始矩阵行向后收集连续纯数字行拼成一条 dltq，避免只取
    首行静默丢段（表象：用户看到 N 孔说明,几何只有第 1 孔）。
    """
    text = re.sub(r"```[a-z]*", "", text).replace("```", "")
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return [], ""

    def _looks_matrix(s):
        s = s.strip()
        return s.startswith("[") or s[:1].isdigit() or s[:1] in "-."

    _EMPTY = ("[]", "［］", "无", "-")

    def _seg_row(s):
        # 可拼接段行：纯数字行且 ≥2 个数字（排除枚举号"1."等单数字行）
        s = s.strip()
        return (s not in _EMPTY and _looks_matrix(s)
                and re.fullmatch(r"[\d,.\s\-]+", s) is not None
                and len(re.findall(r"-?\d+\.?\d*", s)) >= 2)

    def _collect(idx):
        """从第 idx 行(矩阵行)起收集连续段行,返回(dltq, 下一行号)。"""
        dltq = []
        j = idx
        while j < len(lines) and _seg_row(lines[j]):
            dltq.extend(_parse_matrix_line(lines[j]))
            j += 1
        return dltq, j

    if _looks_matrix(lines[0]):
        if lines[0].strip() in _EMPTY:
            return [], "\n".join(lines[1:]).strip()
        dltq, j = _collect(0)
        note = "\n".join(lines[j:]).strip()
        return dltq, note
    # 首行不像矩阵:扫描矩阵行(行首数字且整行仅数字/逗号/空格)
    for idx, l in enumerate(lines):
        ls = l.strip()
        if _looks_matrix(ls) and re.fullmatch(r"[\[\]\d,.\s\-]+", ls):
            dltq, j = _collect(idx)
            if dltq:
                note = "\n".join(lines[:idx] + lines[j:]).strip()
                return dltq, note
    # 无矩阵行:整体当备注
    return [], text.strip()


def translate(text, user_id=None, history=None, feedback=None, recent=None):
    """自然语言 → (数字矩阵 ΔQ, 备注回应) 双通道

    Args:
        text: 用户输入（设计指令或对话）
        user_id: 用户ID（用于 LLM 配额）
        history: 已有对象指称列表 [{seq, names, echo, source}]（供 LLM 引用）
        feedback: 执行层反馈（如干涉详情）——注入为修正指令,重译一版矩阵;
                  该通道只进 LLM 对话,设计者不可见(信息分流)
        recent: 最近对话 [{role,content}]——欠约束提问后的补充轮,补充语
                单独看缺尺寸/对象,带前几轮拼完整约束(2026-09-07)
    Returns:
        dict {dltq: [数字], note: "备注文本", raw: "LLM原始返回",
              ok: bool, error: str}
        ok=True: 矩阵与备注至少其一有效；矩阵含 9999 → ok=False(报警,备注仍带回)

    MCP 取参：几何体参数表经工具 get_geometry_schema 由 LLM 调用查询
    （prompt 不内嵌体元参数细节——单一来源,扩体元只改工具）。
    """
    import json as _json
    from anvil.encoder.codetable import GEOMETRY_SCHEMA_TOOL, get_geometry_schema

    sys_prompt = SYSTEM_PROMPT % prompt_text()
    ctx_text = _context_text(resolve_context(text))
    if ctx_text:
        sys_prompt += "\n\n上下文提示（译码前参考）：\n%s" % ctx_text
    if history:
        refs = []
        for h in history:
            head = "#%d" % h["seq"]
            if h.get("names"):
                head += " %s" % h["names"]  # 角色指称锚(别名集)
            line = head + "｜%s" % h.get("echo", "")
            src = (h.get("source") or "").strip()
            if src:
                line += "（原指令：%s）" % src
            pos = (h.get("pos") or "").strip()
            if pos:
                line += "｜实际占位 %s" % pos  # 心象位置(只读事实,坐标算术交给内核)
            refs.append(line)
        sys_prompt += ("\n\n已有对象指称索引（引用用 990,序号；名称/角色词→序号的唯一权威映射，"
                       "必须按名称或原指令匹配选取，禁止凭空猜序号）：\n%s" % "\n".join(refs))

    messages = [
        {"role": "system", "content": sys_prompt},
    ]
    if recent:
        # 多轮对话格式注入(欠约束补充轮):上轮指令+问句在前,本轮输入
        # 自然成为"补答"——对话模型的强项,比塞 system 文本可靠(2026-09-07)
        for d in recent:
            _role, _c = d.get("role"), (d.get("content") or "")[:400]
            if _role in ("user", "assistant") and _c and _c != text:
                messages.append({"role": _role, "content": _c})
    messages.append({"role": "user", "content": text})
    if feedback:
        messages.append({"role": "user",
                         "content": "（系统执行反馈——上一版矩阵执行失败，按此修正后重新输出完整双通道结果，不要向用户道歉）\n" + feedback})
    tools = [GEOMETRY_SCHEMA_TOOL]
    _trace = []  # 重译过程留痕(失败时持久化到设计日志,供后续优化漂移/失败模式分析)
    # 重译预算2轮(429 配额保护:3轮在 flash 免费档下易触发速率限制)
    for attempt in (1, 2):
        if attempt > 1:
            _trace.append({"round": attempt, "type": "重译"})
        try:
            resp = chat(messages, temperature=0.1, user_id=user_id, tools=tools)
            # MCP 工具循环:LLM 查参数表 → 回填结果 → 续答(至多 3 轮,防打转)
            _loops = 0
            while (resp and resp.choices and getattr(resp.choices[0].message, "tool_calls", None)
                   and _loops < 3):
                _loops += 1
                _msg = resp.choices[0].message
                messages.append({
                    "role": "assistant", "content": _msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in _msg.tool_calls],
                })
                for tc in _msg.tool_calls:
                    try:
                        _args = _json.loads(tc.function.arguments or "{}")
                    except Exception:
                        _args = {}
                    _result = get_geometry_schema(_args.get("name", ""))
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": _json.dumps(_result, ensure_ascii=False),
                    })
                resp = chat(messages, temperature=0.1, user_id=user_id, tools=tools)
            raw = resp.choices[0].message.content.strip() if resp and resp.choices else ""
            dltq, note = _parse_dual(raw)
            if not dltq and not note:
                _trace.append({"round": attempt, "type": "双空"})
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "输出违规：矩阵与备注同时为空。请按格式重发：第一行矩阵([]表示无新增设计)，其后备注。"})
                if attempt < 2:
                    continue
                return {"dltq": [], "note": "", "raw": raw, "ok": False, "_trace": _trace,
                        "error": "译码失败：矩阵与备注同时为空(重译后仍违规)"}
            # 漂移防御:矩阵空但备注含明显设计内容(坐标/尺寸/特征词)——flash 档
            # 偶发把设计指令误判为纯对话 → 违规反馈重译
            if (not dltq and note
                    and re.search(r"孔|凸台|直径|半径|贯穿|长方体|圆柱|球|锥|坐标|×", note)
                    and re.search(r"\d", note)):
                _trace.append({"round": attempt, "type": "空矩阵漂移"})
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "输出违规：这是设计指令，矩阵不可为空。请重发：第一行=完整数字矩阵(按译码表/几何体参数表)，其后备注。"})
                if attempt < 2:
                    continue
                return {"dltq": [], "note": note, "raw": raw, "ok": False, "_trace": _trace,
                        "error": "译码失败：设计指令译出空矩阵(重译后仍漂移)"}
            # 译码正确性校验(确定性,内核裁决) → 重新译码机制(2026-09-06 用户定)
            # 引用存在性一并校验:错引(如清零后惯性引用#1)触发重译而非终败
            if dltq:
                issues = validate_dltq(dltq, text,
                                       alive_seqs={h["seq"] for h in (history or [])})
                if issues:
                    _trace.append({"round": attempt, "type": "校验", "issues": issues[:3]})
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user",
                                     "content": "译码校验未通过：%s。请重新译码：第一行=修正后的完整数字矩阵"
                                                "（体元按几何体参数表写满参数,编号后参数个数必须与参数表一致），其后备注。"
                                                % "；".join(issues[:3])})
                    if attempt < 2:
                        continue
                    # 重译仍不过:技术细节留 internal(服务端日志/排查用),
                    # 用户侧只见 run_round 转译后的友好文案(2026-09-06 用户定)
                    return {"dltq": dltq, "note": note, "raw": raw, "ok": False, "_trace": _trace,
                            "error": "译码校验失败(重译后仍不通过)：%s" % "；".join(issues[:3])}
            if 9999 in dltq:
                _trace.append({"round": attempt, "type": "9999词表缺口"})
                return {"dltq": [], "note": note, "raw": raw, "ok": False, "_trace": _trace,
                        "error": "译码报警：含 9999（无法映射的词）"}
            return {"dltq": dltq, "note": note, "raw": raw, "ok": True, "error": None,
                    "_trace": _trace}
        except Exception as e:
            return {"dltq": [], "note": "", "raw": "", "ok": False,
                    "_trace": _trace + [{"round": attempt, "type": "异常", "error": str(e)[:120]}],
                    "error": "LLM调用失败: %s" % e}
    return {"dltq": [], "note": "", "raw": "", "ok": False, "error": "译码失败"}
