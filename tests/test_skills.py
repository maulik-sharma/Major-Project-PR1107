"""Tests for Skills loading, multi-folder sub-resources, import, persistence, and progressive disclosure."""

from pathlib import Path
from modelmesh.core.skills import SkillLoader, get_load_skill_tool


def test_skill_loader_basic(tmp_path: Path) -> None:
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


def test_multi_folder_skill_and_resources(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    fastapi_dir = skills_dir / "fastapi"
    refs_dir = fastapi_dir / "references"
    refs_dir.mkdir(parents=True)

    (fastapi_dir / "SKILL.md").write_text(
        """---
name: fastapi
description: FastAPI best practices.
---
# FastAPI Guide
See references for streaming and dependencies.
""",
        encoding="utf-8",
    )
    (refs_dir / "streaming.md").write_text("# Streaming Guide\nUse SSE or JSON Lines.", encoding="utf-8")
    (refs_dir / "dependencies.md").write_text("# Dependencies Guide\nUse Annotated.", encoding="utf-8")

    loader = SkillLoader(skills_dir=skills_dir)
    skill = loader.get_skill("fastapi")
    assert skill is not None
    assert "references/streaming.md" in skill.resources
    assert "references/dependencies.md" in skill.resources

    # Check resource reading
    stream_content = skill.get_resource("references/streaming.md")
    assert stream_content is not None
    assert "Use SSE or JSON Lines" in stream_content

    # Path traversal protection
    assert skill.get_resource("../../../etc/passwd") is None

    # Load skill tool handler with resources
    spec, handler = get_load_skill_tool(loader)
    main_res = handler(name="fastapi")
    assert "available_resources" in main_res
    assert "references/streaming.md" in main_res["available_resources"]

    # Load specific resource
    res_content = handler(name="fastapi", resource="references/streaming.md")
    assert res_content["resource"] == "references/streaming.md"
    assert "Use SSE or JSON Lines" in res_content["content"]

    # Non-existent resource
    bad_res = handler(name="fastapi", resource="references/nonexistent.md")
    assert "error" in bad_res


def test_skill_enable_disable_and_persistence(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    state_file = tmp_path / "custom_state.json"
    loader = SkillLoader(skills_dir=skills_dir, state_file=state_file)

    loader.create_skill(
        name="formatter",
        description="Formats code.",
        body="Use black or ruff.",
    )
    assert len(loader.list_skills()) == 1
    assert loader.get_skill("formatter").enabled is True

    # Disable skill
    loader.set_enabled("formatter", False)
    assert loader.get_skill("formatter").enabled is False
    assert len(loader.list_skills(only_enabled=True)) == 0
    assert loader.format_system_prompt_index() == ""

    # Check disabled tool execution
    spec, handler = get_load_skill_tool(loader)
    res = handler(name="formatter")
    assert "disabled" in res["error"]

    # New loader reloads saved state
    loader2 = SkillLoader(skills_dir=skills_dir, state_file=state_file)
    assert loader2.get_skill("formatter").enabled is False


def test_import_and_delete_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    loader = SkillLoader(skills_dir=skills_dir)

    # Import single file
    src_file = tmp_path / "my_custom_skill.md"
    src_file.write_text(
        """---
name: custom-sql
description: SQL optimization guidelines.
---
# SQL Optimizer
Use indexes wisely.
""",
        encoding="utf-8",
    )
    imported = loader.import_skill_file(src_file)
    assert imported is not None
    assert imported.name == "custom-sql"
    assert loader.get_skill("custom-sql") is not None

    # Import entire directory
    src_folder = tmp_path / "external-tool"
    (src_folder / "sub").mkdir(parents=True)
    (src_folder / "SKILL.md").write_text("---\nname: external-tool\ndescription: External.\n---\n# Ext", encoding="utf-8")
    (src_folder / "sub" / "guide.md").write_text("Detailed guide.", encoding="utf-8")

    imported_folder = loader.import_skill_folder(src_folder)
    assert imported_folder is not None
    assert imported_folder.name == "external-tool"
    assert "sub/guide.md" in imported_folder.resources

    # Delete skill
    deleted = loader.delete_skill("custom-sql")
    assert deleted is True
    assert loader.get_skill("custom-sql") is None
