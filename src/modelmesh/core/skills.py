"""Skills management module for on-demand progressive disclosure of prompt instructions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from modelmesh.core.types import ToolSpec


@dataclass
class Skill:
    """A loaded skill instruction definition."""
    name: str
    description: str
    body: str
    path: Path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "path": str(self.path),
        }


class SkillLoader:
    """Loads skills from a directory of folders containing SKILL.md."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self.skills_dir = skills_dir or (Path.cwd() / "skills")
        self._skills: Dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        """Scan skills directory and load all SKILL.md files."""
        self._skills.clear()
        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            return

        for item in self.skills_dir.iterdir():
            if item.is_dir():
                skill_file = item / "SKILL.md"
                if skill_file.exists():
                    skill = self._parse_skill_file(skill_file)
                    if skill:
                        self._skills[skill.name] = skill

    def _parse_skill_file(self, file_path: Path) -> Optional[Skill]:
        try:
            content = file_path.read_text(encoding="utf-8")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter_str = parts[1]
                    body = parts[2].strip()
                    meta = yaml.safe_load(frontmatter_str) or {}
                    name = meta.get("name", file_path.parent.name)
                    desc = meta.get("description", "")
                    return Skill(name=name, description=desc, body=body, path=file_path)
            # Fallback without frontmatter
            return Skill(
                name=file_path.parent.name,
                description=f"Skill from {file_path.parent.name}",
                body=content.strip(),
                path=file_path,
            )
        except Exception:
            return None

    def list_skills(self) -> List[Skill]:
        """Return all loaded skills."""
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def format_system_prompt_index(self) -> str:
        """Generate progressive disclosure index to prepend/append to system prompt."""
        skills = self.list_skills()
        if not skills:
            return ""

        lines = [
            "Available Skills (call 'load_skill' with the skill name for full instructions):"
        ]
        for s in skills:
            lines.append(f"- {s.name}: {s.description}")
        return "\n".join(lines)


def get_load_skill_tool(loader: SkillLoader) -> Tuple[ToolSpec, Callable[..., Any]]:
    """Return ToolSpec and handler function for the 'load_skill' tool."""
    spec = ToolSpec(
        name="load_skill",
        description="Load complete instructions and workflow details for an available skill.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to load.",
                }
            },
            "required": ["name"],
        },
    )

    def _load_skill(name: str) -> Dict[str, Any]:
        skill = loader.get_skill(name)
        if skill:
            return {
                "name": skill.name,
                "description": skill.description,
                "instructions": skill.body,
            }
        return {"error": f"Skill '{name}' not found."}

    return spec, _load_skill
