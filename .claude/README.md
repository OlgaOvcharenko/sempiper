# Claude Configuration for sempipes_demo

This folder contains rules, guidelines, and configuration for using Claude (via API, Projects, or other integrations) with the sempipes_demo project.

## Purpose

These files are designed to help Claude understand the project structure, constraints, and development guidelines when working on this codebase outside of Cursor IDE.

## Structure

- **`rules/`** — Project rules and constraints that should always be followed
- **`project-context.md`** — High-level project context and architecture overview
- **`system-prompt.md`** — System prompt template for Claude API integrations

## Usage

### For Claude.ai Projects

1. Create a new Project in Claude.ai
2. Add the files from `.claude/rules/` as Project knowledge
3. Use the content from `project-context.md` in the Project's custom instructions

### For Claude API

Use the `system-prompt.md` content as your system prompt, and include relevant rule files from `rules/` as context when making API calls.

### For Other Integrations

Reference these files when setting up Claude in any development environment to maintain consistency with project guidelines.

## Rules Overview

1. **no-edit-sempipes.md** — Never modify the `sempipes/` symlink folder
2. **commit-conventions.md** — Git commit style guidelines
3. **setup-and-run.md** — Project setup and execution instructions
4. **demo-three-panel-design.md** — Core UI/UX design principles
5. **demo-tests-no-real-llms.md** — Testing guidelines (no real LLM calls)
6. **run-tests-after-edits.md** — Test execution requirements
7. **demo-inspired-by-sempipes-notebooks.md** — Design inspiration source
8. **no-bypass-sempipes-operators.md** — API usage constraints
