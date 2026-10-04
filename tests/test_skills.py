"""Tests for Skills loading and progressive disclosure."""

from pathlib import Path
from modelmesh.core.skills import SkillLoader, get_load_skill_tool


def test_skill_loader(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill1_dir = skills_dir / "summarizer"
    skill1_dir.mkdir(parents=True)

    skill_md = skill1_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: summarizer
description: Summarizes complex documents into bullet points.
---
# Summary Instructions
Always summarize into 3 key takeaways.
""",
        encoding="utf-8",
    )

    loader = SkillLoader(skills_dir=skills_dir)
    skills = loader.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "summarizer"
    assert "Summarizes complex documents" in skills[0].description
    assert "3 key takeaways" in skills[0].body

    # Format system prompt index
    index_prompt = loader.format_system_prompt_index()
    assert "Available Skills" in index_prompt
    assert "- summarizer: Summarizes complex documents" in index_prompt

    # Load skill tool handler
    spec, handler = get_load_skill_tool(loader)
    assert spec.name == "load_skill"
    res = handler(name="summarizer")
    assert res["name"] == "summarizer"
    assert "3 key takeaways" in res["instructions"]

    # Nonexistent skill
    bad_res = handler(name="missing")
    assert "error" in bad_res
