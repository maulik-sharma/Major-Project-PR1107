# Interactive Rebase Playbook

## Safe Interactive Rebasing
To clean up recent commits on your local branch:
```bash
git rebase -i HEAD~N
```

Commands:
- `pick`: Use commit as is
- `reword`: Change commit message
- `squash`: Meld into previous commit and combine messages
- `fixup`: Meld into previous commit discarding this commit's log message
- `drop`: Remove commit

## Resolving Conflicts
```bash
# 1. Edit conflicted files and resolve conflict markers
# 2. Stage resolved files
git add <resolved-file>
# 3. Continue rebase
git rebase --continue
# If you need to abort cleanly
git rebase --abort
```
