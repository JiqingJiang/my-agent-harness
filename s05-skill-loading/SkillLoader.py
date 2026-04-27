import re
import yaml
from pathlib import Path


class SkillLoader:
    def __init__(self, skills_dir="skills"):
        self.skills = {}
        self._load_all(skills_dir)

    def _parse_frontmatter(self, text: str) -> tuple:
        """分割 SKILL.md 的 frontmatter 和 body。"""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text
        try:
            meta = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        return meta, match.group(2).strip()

    def _load_all(self, skills_dir: str):
        """扫描目录下所有 SKILL.md，解析后存入 self.skills。"""
        for f in sorted(Path(skills_dir).rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            desc = meta.get("description", "No description")
            self.skills[name] = {
                "name": name,
                "description": desc,
                "body": body,
            }

    def get_descriptions(self) -> str:
        """Layer 1：返回所有 skill 的简短描述（给 system prompt 用）。"""
        lines = []
        for name, skill in self.skills.items():
            lines.append(f"  - {name}: {skill['description']}")
        return "\n".join(lines)

    def get_content(self, name: str) -> str:
        """Layer 2：返回某个 skill 的完整内容（给 tool_result 用）。"""
        skill = self.skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
