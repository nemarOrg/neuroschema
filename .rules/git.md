# Git Rules

## Commits
- Atomic commits, focused changes
- Messages concise, no emojis
- Feature branches for multi-step work
- Never amend published commits

## Branching
- `main` is the default branch
- Feature branches: `feature/short-description`
- Bugfix branches: `fix/short-description`

## Pre-commit
- Ruff check with `--fix` and `--unsafe-fixes` on staged files
- Ruff format on staged files
