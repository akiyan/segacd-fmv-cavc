---
name: finish
description: "Merge the current branch lineage into main, push main, delete only the starting branch and resolve related issues when the user invokes /finish or explicitly requests that finish workflow."
---

# Finish a branch lineage

An explicit invocation authorizes the described normal merge/push/delete/issue
workflow. It does not authorize force-push, loss of unrelated work or closing
unfinished issues. `--force-close N,...` and `--force-close-related` authorize
only the named/related issue closure even with documented remaining work.

1. Record starting branch/SHA, status, worktrees and upstream. Fetch origin.
   Preserve unrelated edits; use an isolated integration worktree if needed.
   Commit task changes first only when that is already authorized. Do not stash,
   reset or absorb unrelated work. Require a clear target (normally main).
2. Resolve the ancestor chain from PR base links, then branch tips that are
   ancestors of the starting SHA and descendants of origin/main. Order by
   ancestry and deduplicate local/remote aliases. Ask only for genuinely
   ambiguous lineage; never merge every plausible branch. Report the chain.
3. Collect related issues from explicit branch numbers, PR closing references
   and unambiguous closing commits. Read remaining requirements before closure.
4. Integrate oldest to newest on a temporary branch from fresh origin/main.
   Use Japanese merge messages and human attribution. Resolve mechanical,
   unambiguous conflicts within scope; preserve a concrete conflict for the
   user if deciding it would change intent. Do not force reset user branches.
5. Run checks relevant to the integration. Preserve failures and fix the
   underlying cause within scope; no ritual all-project rebuild/re-encode.
6. Advance main safely and push normally. If main advanced remotely, integrate
   that change and validate affected paths; never force-push. Fetch and prove
   the starting SHA is an ancestor of origin/main before cleanup.
7. Only after containment succeeds: delete the original starting branch locally
   with `git branch -d` and remotely, keeping ancestor branches. Do not disturb
   another active worktree. Close/comment on integrated PRs and related issues
   with accurate Japanese status. Leave incomplete issues open unless explicitly
   force-closed. Do not fabricate successful API operations.

Report final local/remote main SHA, branch cleanup, relevant checks and issue/PR
actions. If blocked, retain a recoverable integration state and name the exact
unfinished action. No repeated confirmation is needed for authorized steps.
