# MCP Prompts

Six user-selected prompt templates ("slash commands") built on top of the
tool registry documented in [`API.md`](API.md). Prompts are a data-plane
artifact like tools (see `DESIGN.md` §Tools, "the law"): the server never
calls an LLM to build them — a `PromptSpec` just fills a fixed instruction
template with the caller's arguments and hands it back as a single
`user`-role message. The calling assistant reads it, chains the named
tools, and exercises judgment.

Defined in `ewsmcp/prompts.py`, wired in `ewsmcp/server.py` via the
standard `prompts/list` and `prompts/get` MCP methods (available over
stdio and Streamable HTTP, same as tools). Tier-filtered exactly like the
tool registry: a prompt is only listed if every tool it recommends is at
or below the deployment's `EWS_CAPABILITY_TIER`.

| Prompt | Min tier | Arguments | Tools it chains |
|---|---|---|---|
| `morning-brief` | `read` | `timeframe` (optional, default `today`) | `get_mailbox_overview`, `waiting_on`, `list_tasks` |
| `health-check` | `read` | — | `get_server_status` |
| `draft-reply` | `draft` | `message_id` (required), `tone`, `key_points` | `get_message`, `create_draft` |
| `schedule-meeting` | `draft` | `attendees` (required), `duration_minutes` (required), `timeframe`, `title` | `check_availability`, `create_event` |
| `set-away-message` | `draft` | `start`, `end`, `message` (all required) | `get_oof_settings`, `set_oof` |
| `send-draft-checklist` | `full` | `draft_id` (required) | `send_draft` (two-phase confirm) |

`prompts/get` raises `ValueError` for an unknown prompt name or a missing
required argument — the same fail-fast behavior as a tool call with a bad
schema, surfaced by the MCP SDK to the client.

Tested in `tests/test_prompts.py`: prompt count, tier filtering against the
named tools' own tiers, argument default/validation, and end-to-end
`prompts/list` / `prompts/get` through the real `Server` instance.
