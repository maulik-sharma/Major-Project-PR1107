"""Skills management module for on-demand progressive disclosure of prompt instructions."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

from modelmesh.core.types import ToolSpec


@dataclass
class Skill:
    """A loaded skill instruction definition with optional supporting resources."""

    name: str
    description: str
    body: str
    path: Path
    folder_path: Path
    enabled: bool = True
    resources: Dict[str, Path] = field(default_factory=dict)

    def get_resource(self, rel_path: str) -> Optional[str]:
        """Safely read and return text content of a sub-resource file."""
        normalized = os.path.normpath(rel_path).lstrip("/\\")
        target_path = (self.folder_path / normalized).resolve()

        # Prevent directory traversal outside the skill folder
        try:
            target_path.relative_to(self.folder_path.resolve())
        except ValueError:
            return None

        if target_path.exists() and target_path.is_file():
            try:
                return target_path.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert skill to a serializable dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "path": str(self.path),
            "folder_path": str(self.folder_path),
            "enabled": self.enabled,
            "resources": list(self.resources.keys()),
        }


class SkillLoader:
    """Loads and manages skills with multi-file sub-resources and state persistence."""

    def __init__(
        self,
        skills_dir: Optional[Path] = None,
        state_file: Optional[Path] = None,
    ) -> None:
        self.skills_dir = skills_dir or (Path.cwd() / "skills")
        self.state_file = state_file or (self.skills_dir / ".skills_state.json")
        self._skills: Dict[str, Skill] = {}
        self._enabled_states: Dict[str, bool] = {}
        self.reload()

    def _load_state(self) -> None:
        """Load enabled/disabled states from persistence file."""
        if self.state_file.exists() and self.state_file.is_file():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._enabled_states = {k: bool(v) for k, v in data.items()}
            except Exception:
                self._enabled_states = {}

    def _save_state(self) -> None:
        """Persist enabled/disabled states to file."""
        try:
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(self._enabled_states, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def reload(self) -> None:
        """Scan skills directory and load all SKILL.md files and sub-resources."""
        self._load_state()
        self._skills.clear()
        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            return

        for item in sorted(self.skills_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("."):
                skill_file = item / "SKILL.md"
                if not skill_file.exists():
                    # Check case-insensitive skill.md
                    for cand in item.iterdir():
                        if cand.name.lower() == "skill.md":
                            skill_file = cand
                            break

                if skill_file.exists():
                    skill = self._parse_skill_folder(item, skill_file)
                    if skill:
                        self._skills[skill.name] = skill

    def _parse_skill_folder(self, folder: Path, skill_file: Path) -> Optional[Skill]:
        try:
            content = skill_file.read_text(encoding="utf-8")
            name = folder.name
            desc = f"Skill from {folder.name}"
            body = content.strip()

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter_str = parts[1]
                    body = parts[2].strip()
                    meta = yaml.safe_load(frontmatter_str) or {}
                    name = str(meta.get("name", folder.name))
                    desc = str(meta.get("description", desc))

            # Discover all sub-resources (excluding SKILL.md, hidden files, pycache)
            resources: Dict[str, Path] = {}
            for subpath in folder.rglob("*"):
                if subpath.is_file() and not subpath.name.startswith("."):
                    if subpath.name.lower() == "skill.md" and subpath.parent == folder:
                        continue
                    if "__pycache__" in subpath.parts:
                        continue
                    rel = subpath.relative_to(folder).as_posix()
                    resources[rel] = subpath

            enabled = self._enabled_states.get(name, True)

            return Skill(
                name=name,
                description=desc,
                body=body,
                path=skill_file,
                folder_path=folder,
                enabled=enabled,
                resources=resources,
            )
        except Exception:
            return None

    def list_skills(self, only_enabled: bool = False) -> List[Skill]:
        """Return all loaded skills, optionally filtering to enabled only."""
        if only_enabled:
            return [s for s in self._skills.values() if s.enabled]
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Set enabled status of a skill and persist state."""
        skill = self._skills.get(name)
        if skill:
            skill.enabled = enabled
            self._enabled_states[name] = enabled
            self._save_state()
            return True
        return False

    def import_skill_file(self, source_file: Path) -> Optional[Skill]:
        """Import a single markdown/yaml skill file into its own folder."""
        if not source_file.exists() or not source_file.is_file():
            return None

        content = source_file.read_text(encoding="utf-8")
        name = source_file.stem
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                meta = yaml.safe_load(parts[1]) or {}
                name = str(meta.get("name", name))

        folder_name = name.lower().replace(" ", "-")
        target_dir = self.skills_dir / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "SKILL.md").write_text(content, encoding="utf-8")

        self.reload()
        return self.get_skill(name)

    def import_skill_folder(self, source_folder: Path) -> Optional[Skill]:
        """Import a directory containing SKILL.md and optional sub-resources."""
        if not source_folder.exists() or not source_folder.is_dir():
            return None

        target_dir = self.skills_dir / source_folder.name
        if target_dir.exists() and target_dir.resolve() != source_folder.resolve():
            shutil.rmtree(target_dir)

        if target_dir.resolve() != source_folder.resolve():
            shutil.copytree(source_folder, target_dir)

        self.reload()
        # Find skill in this folder
        for s in self._skills.values():
            if s.folder_path.resolve() == target_dir.resolve():
                return s
        return None

    def create_skill(
        self,
        name: str,
        description: str,
        body: str,
        subfiles: Optional[Dict[str, str]] = None,
    ) -> Skill:
        """Create a new skill directory with frontmatter and optional subfiles."""
        clean_name = name.strip().lower().replace(" ", "-")
        folder = self.skills_dir / clean_name
        folder.mkdir(parents=True, exist_ok=True)

        frontmatter = f"---\nname: {name}\ndescription: {description}\n---\n\n"
        full_content = frontmatter + body.strip() + "\n"
        (folder / "SKILL.md").write_text(full_content, encoding="utf-8")

        if subfiles:
            for rel_path, content in subfiles.items():
                dest_file = folder / rel_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                dest_file.write_text(content, encoding="utf-8")

        self.reload()
        return self.get_skill(name) or Skill(
            name=name,
            description=description,
            body=body,
            path=folder / "SKILL.md",
            folder_path=folder,
            enabled=True,
        )

    def delete_skill(self, name: str) -> bool:
        """Delete a skill and its folder."""
        skill = self._skills.get(name)
        if not skill:
            return False

        if skill.folder_path.exists():
            shutil.rmtree(skill.folder_path)

        self._skills.pop(name, None)
        self._enabled_states.pop(name, None)
        self._save_state()
        return True

    def format_system_prompt_index(self) -> str:
        """Generate progressive disclosure index of enabled skills for the system prompt."""
        skills = self.list_skills(only_enabled=True)
        if not skills:
            return ""

        lines = [
            "Available Skills (call 'load_skill' with the skill name to get detailed instructions and references):"
        ]
        for s in skills:
            ref_note = ""
            if s.resources:
                ref_names = ", ".join(list(s.resources.keys())[:3])
                if len(s.resources) > 3:
                    ref_names += f", +{len(s.resources) - 3} more"
                ref_note = f" (Sub-resources: {ref_names})"
            lines.append(f"- {s.name}: {s.description}{ref_note}")
        return "\n".join(lines)


def get_load_skill_tool(loader: SkillLoader) -> Tuple[ToolSpec, Callable[..., Any]]:
    """Return ToolSpec and handler function for the 'load_skill' tool supporting multi-file skills."""
    spec = ToolSpec(
        name="load_skill",
        description="Load complete instructions, workflows, and optional reference files for an available skill.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to load.",
                },
                "resource": {
                    "type": "string",
                    "description": "Optional relative path to a sub-resource file within the skill (e.g. 'references/streaming.md').",
                },
            },
            "required": ["name"],
        },
    )

    def _load_skill(name: str, resource: Optional[str] = None) -> Dict[str, Any]:
        skill = loader.get_skill(name)
        if not skill or not skill.enabled:
            return {"error": f"Skill '{name}' not found or is currently disabled."}

        if resource:
            content = skill.get_resource(resource)
            if content is not None:
                return {
                    "name": skill.name,
                    "resource": resource,
                    "content": content,
                }
            return {
                "error": f"Resource '{resource}' not found in skill '{name}'.",
                "available_resources": list(skill.resources.keys()),
            }

        result: Dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "instructions": skill.body,
        }
        if skill.resources:
            result["available_resources"] = list(skill.resources.keys())
            result["note"] = (
                "To load any specific sub-resource/reference file, call "
                f"load_skill(name='{skill.name}', resource='<resource_path>')"
            )
        return result

    return spec, _load_skill
