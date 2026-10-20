---
name: new
description: "Create a task branch from the requested base when the user explicitly asks for a new branch or invokes /new; preserve existing work."
---

# Start a branch task

Inspect status, current branch and recent commits. Use the requested base; absent
one, branch from current HEAD with `codex/<task>`. If the user asks to commit and
push current work first, do that before branching. Do not silently switch main.

Preserve unrelated edits. Existing user authorization may cover committing the
current work; ask only when actual ownership/base ambiguity blocks a safe choice.
Implement coherent changes and run checks appropriate to their risk. Stage the
intended paths, inspect the staged diff and use repository commit attribution/
language. Avoid repeated full suites or cosmetic tests as commit rituals.

Report branch/commits and remaining edits. Push/PR creation follows the user's
scope; creating a branch alone does not request either or imply a main merge.
