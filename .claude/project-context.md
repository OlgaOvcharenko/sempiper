# Claude Project Context

This folder contains Claude-specific rules and settings for the sempipes-demo project.

## About this project

sempipes_demo is a web-based demonstration of the sempipes library for semantic data pipelines with LLM-powered operators.

## Structure

- **rules/** — Project conventions, coding standards, and constraints that should be followed when working with this codebase
- **project-context.md** (this file) — Overview of the Claude configuration

## Using these rules

When working on this project with Claude:
1. Read the relevant rule files in `rules/` to understand project conventions
2. Follow the constraints and patterns described
3. Refer to these rules when making decisions about code changes

## Key principles

- **No edits in sempipes/**: The sempipes folder is a symbolic link to an external repository (read-only)
- **Use sempipes operators**: Don't bypass sempipes API; use operators as intended
- **Fast tests**: All tests must run quickly without real LLM calls
- **Small commits**: Make small, frequent commits with clear one-line messages
- **Three-panel design**: The demo UI follows a specific left-center-right panel layout
