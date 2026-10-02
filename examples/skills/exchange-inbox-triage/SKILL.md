---
name: exchange-inbox-triage
description: >
  Daily inbox triage on top of the ews-mcp 1.1.1 tool surface: morning
  overview, prioritized unread sweep, follow-up tracking (waiting_on),
  and light hygiene (read/categorize/move) — without ever touching a
  send-class tool. Use when the user wants their inbox summarized,
  cleaned up, or wants to know what still needs a reply, without
  drafting or sending anything yet.
---

# Exchange inbox triage

Read-first workflow. Everything here works at the `read` tier; the only
write calls (`update_messages`, `move_messages`, `update_task`) need
`draft` tier and touch metadata only — never content, never a send.

## 1. Start with the overview

Call `get_mailbox_overview` once (`horizon_days` covers today by
default; raise it for a Monday catch-up after a weekend). It returns in
a single payload: `unread_total`, the 10 most recent unread cards, and
today's calendar. Treat this as the spine of the brief — don't re-derive
it from separate calls.

## 2. Prioritize, don't just list

Rank unread mail before presenting it:

1. Meetings starting within the next hour (cross-reference with the
   overview's calendar block) — surface first, they're time-sensitive.
2. Messages from the user's manager, direct reports, or known VIP
   senders (use `find_people` / `get_contact` if you need to confirm who
   someone is).
3. Anything with `has_attachments: true` and a subject implying action
   (contract, invoice, approval, urgent).
4. Everything else, grouped by sender/thread rather than listed flat.

Never present more than the overview already gave you as raw unread
cards — pull additional detail with `get_message` (or `get_thread` for
context across a conversation) only for the items you're about to
discuss, not preemptively for the whole inbox.

## 3. Add what's stalled

- `waiting_on {days: 3}` (or the user's preferred threshold) surfaces
  sent threads nobody replied to — always mention this in a triage
  brief, it's the thing users forget to chase themselves.
- `list_tasks` for open to-dos; call `update_task` to mark done or push
  a due date only when the user explicitly asks — never silently close
  a task because a related email arrived.

## 4. Search instead of guessing

Use `search_messages` for anything not in the last unread page:
structured filters (`sender`, `subject`, `since`/`until`,
`has_attachments`) for known criteria, a free-text `query` (AQS) for
fuzzy asks, `mode: "semantic"` when the deployment has the semantic
tier and the user's request is conceptual ("that email about the Q3
budget") rather than keyword-based. Never combine `query` with the
structured filters — it's a validation error, pick one engine.

`find_similar` (semantic tier only) is useful when the user points at
one message and asks "anything else like this?".

## 5. Hygiene, in bulk, reversibly

- Mark handled threads read: `update_messages {ids: [...], set_read:
  true}` (up to 50 ids per call).
- There's no flag field in this backend — use
  `categories_add: ["Follow up"]` as the visible marker instead, and
  say so if the user asks for "flagging".
- `move_messages` to archive or file triaged mail; ids stay valid after
  the move (no need to re-search).

## Ground rules

- This skill never calls `create_draft`, `send_draft`, or anything
  send/destructive-class — that's `exchange-safe-mail`'s job. If triage
  surfaces something that needs a reply, hand off to that skill instead
  of improvising a draft here.
- A stale id (`not_found`, re-search hint) means the item moved —
  re-run `search_messages` or `get_mailbox_overview`, don't retry the
  same id.
- `source: "cache"` vs `"live"` in every response tells you whether
  you're reading the local mirror or Exchange directly; mention it if
  the user asks "is this up to date?" — pass `fresh: true` to force a
  live read when staleness matters (e.g. right after they say they just
  sent something).
