---
name: exchange-meeting-coordinator
description: >
  Calendar scheduling on top of the ews-mcp 1.0.2 tool surface: finding
  slots that work for every attendee, creating and adjusting events
  without spamming invitees, and handling meeting responses/cancellations
  through the required two-phase confirm. Use when the user wants a
  meeting scheduled, moved, checked for conflicts, or responded to.
---

# Exchange meeting coordinator

Calendar tools split cleanly into silent metadata operations (no
confirm needed) and notification-sending operations (two-phase
confirmed, `full` tier). Get this distinction right before doing
anything — it decides whether you need the user's explicit go-ahead.

## 1. Know the week before proposing anything

- `list_events {start, end}` (default: today → +7d) for the user's own
  agenda; recurring meetings are already expanded into occurrences, so
  don't try to de-duplicate them yourself.
- `get_event {id}` when you need full detail on one meeting — attendee
  response status, body, organizer — before deciding to change or
  cancel it.

## 2. Find a slot that actually works

`check_availability {attendees, start, end, duration_minutes}` proposes
concrete free slots where every listed attendee is free (30-minute
grid, working hours 09:00–17:00 by default via
`working_hours_only`). Resolve names to emails first with `find_people`
if the user gave you names rather than addresses. An empty `slots` list
is a real answer — say so plainly ("nobody has a common free window in
that range") instead of picking a slot anyway.

## 3. Create without notifying, by default

`create_event {subject, start, end, attendees, location, body}` with
the default `send_invitations: false` saves a placeholder — nothing is
emailed, no confirmation needed. This is the right default for
"pencil this in" / draft planning.

Only pass `send_invitations: true` once the user has actually confirmed
the meeting should go out. That flips the call into a two-phase
send-class action:

1. First call (no `confirm_token`) → preview of exactly what will be
   sent, plus a `confirm_token`.
2. Show the preview to the user verbatim (attendees, time, subject) —
   don't paraphrase it away.
3. Only on explicit approval, repeat the identical call with
   `confirm_token` attached.

## 4. Updating an existing event

`update_event {event_id, ...}` with `notify_attendees: false` (default)
is a silent edit — safe for fixing a typo in the location or shifting a
time before anyone external cares. `notify_attendees: true` triggers
the same two-phase confirm as creation with invitations — treat it with
the same care: preview, user approval, then the token call.

## 5. Responding to and cancelling meetings — always two-phase

Both of these send mail to other people and are `full`-tier,
two-phase-confirmed, no exceptions:

- `respond_to_event {event_id, response: accept|decline|tentative,
  message}` — the response goes to the organizer. Preview it, get
  approval, then confirm.
- `cancel_event {event_id, message}` — only for meetings the user
  organizes; sends cancellations to all attendees. This is destructive
  as well as a send — be explicit that this cannot be walked back once
  confirmed, and double-check the user actually organizes the meeting
  (check `get_event`'s organizer field) before offering to cancel it.

Never chain the confirm call automatically after the preview — always
wait for the user's explicit yes, even if they "seem" to have already
decided.

## Ground rules

- `tier_blocked` on any write here means the deployment is running at
  `read` tier — say so, don't retry with different arguments.
- `kill_switch` on a send-class call means `SEND_ENABLED=false` on this
  deployment — it's an intentional operator choice, not a bug.
- `confirm_invalid` means the token expired (10 min TTL) or the
  underlying event/draft changed between preview and confirm — re-run
  the preview step, don't reuse the old token.
- A stale `event_id` (`not_found`) means the calendar moved on —
  re-run `list_events` for a fresh id.
