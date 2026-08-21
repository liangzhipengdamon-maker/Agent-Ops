# Neutral Relay — Checkpoint Evidence Delivery (contract)

This document is the **generic, repository-owned contract** for GovernLoop's
checkpoint evidence delivery. It applies to any project that routes review
checkpoints through the Neutral Relay; it is not specific to any single
downstream repository or ticket system.

Status: **formalized** (implementation in `tools/neutral-relay/neutral_relay.py`,
tests in `tools/neutral-relay/tests/`).

---

## 1. Session routing

- A ChatGPT conversation URL is **task/session-level state**, never permanent
  project configuration.
- The user provides the URL **once per session**. Every later checkpoint in the
  same session reuses it — no repeated asking.
- Session-level state may be passed on the command line (`--conversation-url`,
  `--cdp-port`) or carried in a temporary session config; it is **never written
  back** to the canonical routing config.
- Forbidden: permanent conversation binding, auto-reuse of a previous session's
  URL, auto-selecting the most recent conversation, using another project's
  conversation, or binding to whatever browser tab happens to be open.
- Session cleanup: when the session ends, temporary routing state is removed and
  the canonical config keeps no conversation binding.

## 2. Review checkpoints

The following checkpoints MUST be reported through GovernLoop:

- `NEW_BLOCKER`
- `UNEXPECTED_STATE`
- `BEFORE_DESTRUCTIVE_ACTION`
- `REVIEW_REQUIRED`
- `FINAL_VERIFICATION`

Ordinary progress updates must NOT be sent to the conversation (avoid noise).

## 3. Evidence attachment delivery

- A checkpoint carries concise text **and** the evidence attachment(s) that
  support it. Text and attachments MUST reach the **same** bound conversation.
- A local filesystem path written inside the text **does not count** as
  attachment delivery.
- Delivery success condition:

  ```
  TEXT_RELAY = PASS
  AND REQUIRED_ATTACHMENTS_DELIVERED = PASS
  ```

- If any required attachment is missing or fails to upload, the checkpoint
  result is `CHECKPOINT_DELIVERY_INCOMPLETE` — never report COMPLETE falsely.
  In the relay, any attachment failure aborts the run (non-zero exit) before
  the request text is sent, so a response file is never written.

## 4. Attachment safety

Before attaching a file, the caller verifies:

1. file exists
2. file is relevant to the checkpoint
3. secret scan passes
4. filename / size / sha256 are recorded

Never attach:

- `.env`
- PAT / API keys / tokens / passwords
- credential backups
- browser profiles
- caches
- `node_modules`
- secret-bearing config
- irrelevant raw logs

If a secret-bearing evidence file must be used, generate a **redacted copy**
(`.redacted`) and attach only the redacted copy.

## 5. FINAL_VERIFICATION defaults

`FINAL_VERIFICATION` requires at least:

- the final evidence report
- a manifest / verification artifact
- any additional evidence the checkpoint specifically requires

## 6. CLI behavior

The relay supports evidence attachment upload:

```text
--attachment PATH        repeatable; uploads the file through the ChatGPT file
                         input before sending the request text
--conversation-url URL   session-level conversation override (never persisted)
--cdp-port PORT          session-level CDP port override (never persisted)
```

Transport mechanics:

- uploads use CDP `DOM.setFileInputFiles` on the conversation's `input[type=file]`
  (no user gesture needed);
- after upload the relay **must verify the file name becomes visible in the
  composer DOM** before proceeding (bounded retry);
- upload failure is **fail-closed**: missing file / no file input / upload error /
  not visible all abort the run with a non-zero exit; the request text is never
  sent and no response is written.

Delivery confirmation (three-state model, after clicking Send):

- `--send-confirm-timeout` (default 30s): window while the composer is
  non-empty; the send is deemed not accepted and one safe re-click is allowed.
  If the composer is still non-empty afterwards -> `SEND_NOT_CONFIRMED`
  (fail-closed; guidance explicitly forbids re-running the same request after a
  manual send to avoid duplicate delivery).
- `--send-pending-timeout` (default 90s): if the composer is cleared but the
  thread's user-turn count has not incremented, the relay enters `SEND_PENDING`
  and **never** re-clicks / re-uploads / re-injects (duplicate-delivery risk).
  Confirmation is `DELIVERY_CONFIRMED_PRIMARY` (user turn +1, canonical) or
  `DELIVERY_CONFIRMED_AUXILIARY` (a new assistant turn appears after the send
  AND no assistant turn was streaming before the send). If neither signal
  appears -> `SEND_PENDING_TIMEOUT` (no resend; manual verification guidance).
- The relay never reports PASS or starts wait-for-assistant while the composer
  is still non-empty.

Short usage example (session-level target + attachments):

```bash
python3 tools/neutral-relay/neutral_relay.py \
  --request-file request.txt \
  --output-file response.md \
  --conversation-url <session-url> \
  --attachment report.md \
  --attachment manifest.json
```

## 7. Tests

`tools/neutral-relay/tests/` covers:

- attachment success (single and multiple)
- missing file -> fail-closed
- no file input -> fail-closed
- upload error -> fail-closed
- file name not visible -> fail-closed (after bounded retries)
- multiple attachments go to the same conversation (same session / same input)
- attachment failure never returns COMPLETE (iteration stops at first failure)
- session-level `--conversation-url` override used for the run and canonical
  config untouched
- delivery state machine (`tests/test_send_confirmation.py`): first click
  swallowed -> one safe re-click; still non-empty -> SEND_NOT_CONFIRMED;
  composer cleared + delayed user turn -> SEND_PENDING; pending user +1 ->
  PRIMARY; pending new assistant turn without prior streaming -> AUXILIARY;
  prior streaming rejects the auxiliary signal; pending timeout -> no resend,
  SEND_PENDING_TIMEOUT; never re-click after composer cleared; manual recovery
  guidance contains no "re-run same request"
