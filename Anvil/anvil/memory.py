"""
Memory management — Anvil's persistent memory across sessions and restarts.

Memory is stored in .anvil_comm/memory.md and auto-injected into system prompt.
"""

import os
from datetime import datetime

COMM_DIR = os.path.expanduser("~/develop/elderly-care-robot/DesignTool/Anvil/.anvil_comm")
MEMORY_PATH = os.path.join(COMM_DIR, "memory.md")


def _ensure():
    os.makedirs(COMM_DIR, exist_ok=True)
    if not os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH, "w") as f:
            f.write("# Anvil Memory\n\n> Auto-injected into system prompt at session start.\n\n")


def save(key, content):
    """Save a memory entry.

    Args:
        key: short identifier (e.g. "tool_list", "design_decision_001")
        content: the fact/information to remember
    """
    _ensure()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    existing = ""
    if os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH) as f:
            existing = f.read()

    # Check if key already exists and update in place
    lines = existing.split("\n")
    new_lines = []
    found = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("### ") and key in line:
            # Replace this entry
            new_lines.append("### %s (%s)" % (key, ts))
            i += 1
            while i < len(lines) and not lines[i].startswith("### ") and not lines[i].startswith("# "):
                i += 1
            new_lines.append(content)
            found = True
            continue
        new_lines.append(line)
        i += 1

    if not found:
        new_lines.append("")
        new_lines.append("### %s (%s)" % (key, ts))
        new_lines.append(content)

    with open(MEMORY_PATH, "w") as f:
        f.write("\n".join(new_lines) + "\n")
    return key


def recall(key=None):
    """Read memory entries.

    Args:
        key: specific key, or None for all

    Returns:
        matching memory text
    """
    if not os.path.exists(MEMORY_PATH):
        return "No memory yet."
    with open(MEMORY_PATH) as f:
        content = f.read()
    if key:
        result = []
        lines = content.split("\n")
        in_section = False
        for line in lines:
            if line.startswith("### ") and key in line:
                in_section = True
                result.append(line)
                continue
            if in_section:
                if line.startswith("### ") or line.startswith("# "):
                    break
                result.append(line)
        return "\n".join(result) if result else "No memory for key: " + key
    return content


def list_keys():
    """List all memory keys."""
    if not os.path.exists(MEMORY_PATH):
        return []
    keys = []
    with open(MEMORY_PATH) as f:
        for line in f:
            if line.startswith("### "):
                end = line.find(" (")
                if end < 0:
                    end = line.find("\n")
                key = line[4:end].strip()
                if key:
                    keys.append(key)
    return keys


def inject_context():
    """Get memory context to inject into system prompt.
    Returns markdown string to append to system prompt.
    """
    _ensure()
    memory = recall()
    # Only inject if there's actual content beyond header
    lines = [l for l in memory.split("\n") if l.strip() and not l.startswith(">")]
    if len(lines) <= 2:  # Only header
        return ""
    return "\n\n## 持久记忆（跨会话）\n" + memory


# Tool definitions for agent

def tool_save_memory():
    return {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "保存一条记忆，跨会话持久化。记录重要信息如：当前设计进度、已确认的方案、工具使用心得等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "记忆标识，如 design_progress、confirmed_spec、tool_notes"},
                    "content": {"type": "string", "description": "要记住的内容"}
                },
                "required": ["key", "content"]
            }
        }
    }


def tool_recall_memory():
    return {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "读取记忆。可以查某条具体记忆，也可以看全部。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "记忆标识，不传则看全部"}
                }
            }
        }
    }


def tool_list_memories():
    return {
        "type": "function",
        "function": {
            "name": "list_memories",
            "description": "列出所有记忆的 key，方便查询。",
            "parameters": {"type": "object", "properties": {}}
        }
    }


ALL_MEMORY_TOOLS = [tool_save_memory(), tool_recall_memory(), tool_list_memories()]
