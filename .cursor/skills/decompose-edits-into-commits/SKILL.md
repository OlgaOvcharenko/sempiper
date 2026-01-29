---
name: decompose-edits-into-commits
description: Decomposes current working tree edits into individual small commits following project conventions. Use when the user wants to split changes into multiple commits, create small commits from current edits, or decompose uncommitted changes into logical commits.
---

# Decompose Edits Into Small Commits

When the user asks to decompose current edits into individual small commits (or similar), follow this workflow. Respect the project's commit conventions: small, frequent commits; one-line messages; concrete, not vague.

## Workflow

### 1. Inspect current state

- Run `git status` and `git diff` (and `git diff --staged` if anything is staged) from the repository root.
- List all modified, added, and deleted files and the nature of changes (e.g. "new file", "edit", "rename").

### 2. Group changes logically

- Group edits by **single logical change** (one feature, one fix, one refactor, one doc update, etc.).
- Prefer grouping by:
  - **Topic**: e.g. "add endpoint X" vs "fix bug in Y" vs "update README"
  - **Layer**: e.g. backend vs frontend vs config, when they are independent
- Avoid mixing unrelated changes in one commit. Split config/formatting from behavior when they are separate concerns.

### 3. Propose a commit plan

Output a short **commit plan** before making any commits:

```markdown
## Commit plan

1. **Message**: One-line concrete message  
   **Files**: path/a, path/b  
   **Rationale**: One sentence why this is one logical change.

2. **Message**: ...  
   ...
```

Order commits so that the repo stays buildable after each step (e.g. add types before code that uses them). If the user only asked for a plan, stop here and let them confirm or adjust.

### 4. Create commits one by one

Only if the user wants you to perform the commits (or it was clearly requested):

- For each group in the plan:
  - Stage only the files/hunks for that group: `git add <paths>` or `git add -p` for partial staging.
  - Commit with the one-line message: `git commit -m "Concrete one-line message"`.
- Do **not** squash everything into one commit; keep commits small and separate.
- If a logical group is too large, split it further into smaller commits.

## Message style

- One line, imperative, concrete. Examples:
  - "Add GET /api/compile endpoint"
  - "Fix date formatting in report header"
  - "Add README for Cursor rules"
- Avoid: "Update stuff", "Fix things", "Changes to X".

## When to use this skill

- User says: "split my changes into small commits", "decompose my edits into commits", "make separate commits from current changes", "commit my changes in logical chunks".
- User wants to align with the project rule that asks for small, frequent commits with one-line messages.

## Notes

- If there are no uncommitted changes, say so and suggest they run this after making edits.
- If the repo has a `.cursor/rules/commit-conventions.mdc` (or similar), those rules override any generic advice here; follow them.
