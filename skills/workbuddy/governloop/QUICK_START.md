# QUICK_START — GovernLoop in 3 commands

You never need to invent a session id or a conversation routing config. The
`/governloop` skill detects your repository, derives a task from the branch /
issue id, and creates a session for you.

## Normal workflow

```text
cd <project>
/governloop
```

What happens:

1. the current git repo is detected (from `remote.origin.url`, e.g.
   `owner/repo`);
2. the task is derived (priority: Linear/GitHub issue id in context → current
   branch → explicit title → generated slug);
3. a session id `<PROJECT>-<TASK>-<YYYY-MM-DD>` is generated for you;
4. if the session has no ChatGPT conversation URL yet, you are asked once:

   ```text
   USER_CONVERSATION_SELECTION_REQUIRED
   ```

   Reply with the conversation URL you want to use for this session, e.g.:

   ```text
   /governloop bind https://chatgpt.com/c/6a82b993-f1e0-83ec-9cba-b77ec91e572f
   ```

5. work normally. At the checkpoints `NEW_BLOCKER`, `UNEXPECTED_STATE`,
   `BEFORE_DESTRUCTIVE_ACTION`, `REVIEW_REQUIRED`, `FINAL_VERIFICATION` the
   agent reports a concise summary + the supporting evidence files to that
   conversation automatically. Ordinary progress is not sent.
6. when done:

   ```text
   /governloop end
   ```

   The temp session state is removed; nothing is written to the permanent
   GovernLoop config.

## Status

```text
/governloop status
```

Shows: repo · task · session id · conversation bound (yes/no) · last checkpoint
· temp state path.

## Rules of thumb

- One URL per session, provided once. Reused for every checkpoint in the
  session; never persisted to the canonical config.
- A new session in a different repo never inherits the previous session's URL.
- A local path typed in a checkpoint message is not delivery — evidence files
  are attached as real attachments (secret-scanned first).
