"""Document tool - generate and manage design documents."""

import os
from datetime import datetime


class DocumentTool:
    """Generate and manage design documents within a project."""

    def __init__(self, project_dir):
        self.project_dir = project_dir
        self.docs_dir = os.path.join(project_dir, "docs")
        os.makedirs(self.docs_dir, exist_ok=True)

    def _timestamp(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def save_design_note(self, title, content, section="notes"):
        section_dir = os.path.join(self.docs_dir, section)
        os.makedirs(section_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = title.replace(" ", "_").replace("/", "_")[:50]
        filename = ts + "_" + safe_title + ".md"
        filepath = os.path.join(section_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# " + title + "\n\n")
            f.write("> 生成时间: " + self._timestamp() + "\n\n")
            f.write(content)
        return filepath

    def save_decision(self, question, options, decision, reason, impact=""):
        content = "## 问题\n" + question + "\n\n"
        content += "## 选项\n"
        for i, opt in enumerate(options, 1):
            content += str(i) + ". " + opt + "\n"
        content += "\n## 决策\n" + decision + "\n\n"
        content += "## 理由\n" + reason + "\n\n"
        if impact:
            content += "## 影响\n" + impact + "\n"
        return self.save_design_note("决策_" + decision[:20], content, "decisions")

    def save_changelog(self, change, reason=""):
        content = "## 变更内容\n" + change + "\n\n"
        if reason:
            content += "## 变更原因\n" + reason + "\n"
        return self.save_design_note("变更_" + change[:20], content, "changelog")

    def save_calculation(self, title, formula, inputs, result, notes=""):
        content = "## 公式\n```\n" + formula + "\n```\n\n"
        content += "## 输入参数\n"
        for k, v in inputs.items():
            content += "- " + str(k) + ": " + str(v) + "\n"
        content += "\n## 计算结果\n" + result + "\n\n"
        if notes:
            content += "## 备注\n" + notes + "\n"
        return self.save_design_note("计算_" + title, content, "calculations")

    def list_documents(self, section=None):
        if section:
            search_dir = os.path.join(self.docs_dir, section)
        else:
            search_dir = self.docs_dir
        docs = []
        if os.path.exists(search_dir):
            for root, dirs, files in os.walk(search_dir):
                for f in sorted(files):
                    if f.endswith(".md"):
                        docs.append(os.path.join(root, f))
        return docs
