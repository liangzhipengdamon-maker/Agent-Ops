# QUICK_START — GovernLoop in 3 commands

You never need to invent a session id, a conversation routing config, or a
per-project install. The `/governloop` skill detects your repository, derives a
task from the branch / issue id, and creates a session for you.

## The whole workflow

```text
cd <target-project>

/governloop          # creates/resumes a session, asks for the ChatGPT URL once if missing
                     # ... work normally (agent reports checkpoints automatically) ...
/governloop status   # optional: see repo/task/session/URL/last-checkpoint
/governloop end      # task done: optional FINAL_VERIFICATION + temp state cleanup
```

## What `/governloop` does for you

1. **Detects the current git repo** (from `remote.origin.url`, e.g. `owner/repo`).
2. **Derives the task** (priority: Linear/GitHub issue id in context → current
   branch → explicit title → generated slug).
3. **Generates the session id** `<PROJECT>-<TASK>-<YYYY-MM-DD>` — you never
   type one.
4. **Asks for the ChatGPT conversation URL once** if the session has none yet:

   ```text
   USER_CONVERSATION_SELECTION_REQUIRED
   ```

   Reply with the URL you want to use **for this session only**:

   ```text
   /governloop bind https://chatgpt.com/c/6a82b993-f1e0-83ec-9cba-b77ec91e572f
   ```

5. **Work normally.** At the five review checkpoints the agent automatically
   reports a concise summary + supporting evidence files to that conversation:

   | Checkpoint | When it fires |
   |---|---|
   | `NEW_BLOCKER` | a new blocker is discovered |
   | `UNEXPECTED_STATE` | state differs from what was expected |
   | `BEFORE_DESTRUCTIVE_ACTION` | right before any destructive/mutating action |
   | `REVIEW_REQUIRED` | a decision or review is needed from the reviewer |
   | `FINAL_VERIFICATION` | end of task final verification |

   Ordinary progress is **not** sent (avoid noise).

6. When done:

   ```text
   /governloop end
   ```

   The temp session state is removed; nothing is ever written to the permanent
   GovernLoop config.

## FAQ (the 8 questions)

**1. How do I use it in a different project?**
Just `cd <other-project>` and run `/governloop` again. Everything is derived
from that repo; nothing from the previous project leaks in.

**2. Do I need to reinstall GovernLoop per project?**
**No.** GovernLoop is shared infrastructure installed once. Each project only
gets its own *session state*.

**3. Do I have to find a SESSION ID myself?**
**No.** The session id `<PROJECT>-<TASK>-<YYYY-MM-DD>` is generated
automatically. You never type or look one up.

**4. Do I enter the ChatGPT URL every time?**
**Once per session.** Within the same session every checkpoint reuses it. A new
session (new task or new project) asks once again.

**5. Will a new project inherit the old conversation?**
**No.** Conversation URLs are task/session-level state, never project-level.
A new session in a different repo starts unbounded (no inherited URL).

**6. When does the agent automatically report to GPT?**
Only at the five checkpoints: `NEW_BLOCKER`, `UNEXPECTED_STATE`,
`BEFORE_DESTRUCTIVE_ACTION`, `REVIEW_REQUIRED`, `FINAL_VERIFICATION`.

**7. Are evidence files sent automatically?**
Yes — for required checkpoints the agent attaches the relevant, secret-scanned
evidence files per the attachment policy. A local path typed in the text does
**not** count as delivery. If the relay does not support attachments, the file
content is inlined into the message and the delivery status says so honestly.

**8. What happens when the session ends?**
`/governloop end` sends `FINAL_VERIFICATION` (optional, `--final`) and removes
the temp session state. The canonical routing config is never modified.

## Status

```text
/governloop status
```

Shows: repo · task · session id · conversation bound (yes/no) · last checkpoint
· temp state path.

## Rules of thumb

- One URL per session, provided once; reused for every checkpoint in that
  session; never persisted to the canonical config.
- A new session in a different repo never inherits the previous session's URL.
- A local path typed in a checkpoint message is not delivery — evidence files
  are attached as real attachments (secret-scanned first), or inlined with an
  explicit degradation note when the relay lacks attachment support.
