# No Edits in sempipes/

**Always apply this rule**

The `sempipes/` folder in this project is a **symbolic link** to the external `sempipes` repository (sibling folder). It is read-only for this project.

## Rule

- **Do not** create, edit, modify, or delete any files or content under `sempipes/`.
- **Do not** suggest changes that would alter code, config, or assets inside `sempipes/`.
- You may **read** files under `sempipes/` for reference or context only.

If the user needs changes in the sempipes codebase, direct them to open or work in the actual sempipes repository, not via this symlink.
