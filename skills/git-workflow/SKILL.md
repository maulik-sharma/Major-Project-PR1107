---
name: git-workflow
description: Professional Git workflows, trunk-based development, conventional commits, and interactive rebase safety.
---

# Git Workflow Specialist

Best practices for maintaining a clean, linear, and bisectable Git history.

## Golden Rules
1. **Atomic Commits**: Each commit should represent one logical change with tests.
2. **Never Rebase Shared History**: Rebase and squash feature branches locally before merging; never force push main/shared branches.
3. **Descriptive Messages**: Follow conventional commits (`feat:`, `fix:`, `refactor:`, `test:`).

## References
- See [Conventional Commits](references/conventional_commits.md) for commit types, scopes, and breaking change syntax.
- See [Interactive Rebase Playbook](references/rebase_playbook.md) for squash, fixup, and conflict resolution recipes.
