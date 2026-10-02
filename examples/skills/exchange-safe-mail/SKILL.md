---
name: exchange-safe-mail
description: >
  Draft-first, safety-gated mail composition and sending on the ews-mcp
  1.1.1 tool surface — including out-of-office replies. Use whenever the
  user wants to send, reply to, or forward an email, or set an
  auto-reply: this skill enforces the draft → preview → confirm chain
  and explains every safety rejection (kill-switch, recipient guard,
  rate cap, stale token) instead of retrying blindly.
---

# Exchange safe mail

The server enforces a hard rule this skill must never try to work
around: **the only way mail leaves the mailbox is `create_draft` →
`send_draft`**. There is no one-shot send tool, on purpose. Composition
judgment (what to say, tone, who to cc) is entirely the calling
assistant's job — the server only stores, previews, and gates the send.

## 1. Compose as a draft, always

`create_draft {mode, reply_to, to, cc, bcc, subject, body, importance}`:

- `mode: "new"` needs `to` + `body` (and usually `subject`).
- `mode: "reply"` / `"reply_all"` need `reply_to` (the original
  message's id) — the server quotes the original server-side, don't
  paste it into `body` yourself.
- `mode: "forward"` needs `reply_to` and `to`.
- `body` is plain text; the server wraps it in minimal HTML — don't
  hand-author HTML.

Write the actual content yourself — subject line, tone, structure. The
tool call only returns `draft_id` and a preview; nothing has been sent
at this point, so there is no rush and no risk in getting it right
before moving on.

## 2. Let the user review before anything is final

Show the draft's preview to the user in plain language: recipients,
subject, and the gist of the body. If they want changes,
`update_draft {draft_id, ...}` with only the fields that changed —
don't resend the whole draft. `delete_draft {draft_id}` moves an
abandoned draft to trash (recoverable); it only works on items actually
in `f:drafts`.

## 3. Sending is always two-phase and content-bound

`send_draft {draft_id}`:

1. Call without `confirm_token` → the server fetches the CURRENT draft
   and returns its real `to/cc/bcc/subject/body_snippet/
   attachment_count` plus a `confirm_token` bound (HMAC) to that exact
   content.
2. **Re-check that preview against the server's response, not your
   memory of what you wrote** — it is the ground truth. If anyone
   edited the draft between steps, the token silently goes stale.
3. Only after explicit user approval, call `send_draft` again with the
   identical `draft_id` and the `confirm_token`.
4. Pass a stable `idempotency_key` if there's any chance of a retry
   (flaky connection, user asking "did that go through?") — a replay
   with the same key returns the original receipt instead of sending a
   second copy.

Never skip straight to the confirmed call because "the draft looked
right a minute ago" — re-preview every time, tokens are single-use and
TTL-limited (`CONFIRM_TTL_SECONDS`, default 600s).

## 4. Out-of-office replies follow the same discipline

`set_oof {state, internal_reply, external_reply, start, end}` is
send-class (it's externally visible) and two-phase confirmed exactly
like `send_draft`: preview first, confirm second. `state: "scheduled"`
requires `start`/`end`. If `external_reply` is omitted it defaults to
`internal_reply` — call this out to the user if they wanted a different
external message (e.g. hiding internal project details from outside
senders). Check `get_oof_settings` first if the user just wants to know
the current state — that call is read-only and needs no confirm.

## 5. Read every rejection's `hint` before retrying

| error | what actually happened | what to do |
|---|---|---|
| `kill_switch` | this deployment has sending disabled (`SEND_ENABLED=false`) | tell the user plainly; do not retry, it will not start working |
| `tier_blocked` | deployment tier is below `draft`/`full` for this tool | explain the deployment's intentional limit |
| `recipient_blocked` | an address failed the allow/deny list, checked on both the call's arguments and the draft's resolved recipients | tell the user which address and that it's a policy decision, not a typo to fix |
| `confirm_invalid` | token expired, already used, or content changed since preview | re-run the preview step (no `confirm_token`), don't reuse the old one |
| `rate_capped` | `EWS_MAX_SENDS_PER_HOUR` reached | surface `retry_after_s` to the user instead of retrying in a loop |
| `not_found` | draft/message id went stale | re-fetch (`search_messages` / re-list drafts), then redo the flow |

## Ground rules

- Never propose a workaround for `kill_switch` or `recipient_blocked` —
  they are deliberate operator policy on this deployment, not bugs to
  route around.
- Every send-class action is hash-chain audited server-side; there is
  no "undo" once step 3/4's confirmed call succeeds — get real user
  approval on the preview, not on your paraphrase of it.
