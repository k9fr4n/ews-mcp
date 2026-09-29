# EWS MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docker Image](https://img.shields.io/badge/ghcr.io-ews--mcp-blue?logo=docker)](https://github.com/k9fr4n/ews-mcp/pkgs/container/ews-mcp)

> A Model Context Protocol server that gives an LLM assistant **real,
> typed control of a Microsoft Exchange mailbox** — mail, calendar,
> people, tasks, drafts and (explicitly gated) sending — speaking EWS
> natively. No Graph proxy, no Microsoft 365 connector. Works with
> Claude Code, Claude Desktop, Open WebUI, and any other MCP client.

> This is an independent fork of [`azizmazrou/ews-mcp`](https://github.com/azizmazrou/ews-mcp).
> Development, releases, and container images for this fork are maintained
> separately under [`k9fr4n/ews-mcp`](https://github.com/k9fr4n/ews-mcp).

## The server

This repository contains one implementation, published as version **1.1.0**.
It provides a consolidated 28-tool
surface, short alias IDs, token-lean responses, a cache-first local mirror
with Arabic-correct full-text search, and centralized safety gates.

## Quick start — locally over stdio

No Docker needed. The MCP client starts the server as a child process;
it inherits your machine's network (VPNs included), and nothing listens
on any port.

```bash
git clone https://github.com/k9fr4n/ews-mcp.git && cd ews-mcp
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install .
```

Then register it with Claude Code:

```bash
claude mcp add exchange \
  -e EWS_SERVER_URL="https://mail.example.com/EWS/Exchange.asmx" \
  -e EWS_EMAIL="user@example.com" \
  -e EWS_USERNAME="user" -e EWS_PASSWORD="…" \
  -- /absolute/path/to/.venv/bin/ewsmcp
```

Claude Desktop and other clients: same command + env in a config block —
see the [full usage guide](docs/USAGE.md#quick-start--run-it-locally-over-stdio-no-docker).
Defaults are safe: `draft` tier, sending disabled.

## Docker / HTTP (server deployments)

When the server runs on a host that can reach Exchange directly:

```bash
cp .env.example .env
# Pin an exact release tag.
docker run -d --name ews-mcp -p 8000:8000 --env-file .env \
  -v ewsmcp-data:/data ghcr.io/k9fr4n/ews-mcp:v1.1.0
```

The server serves Streamable HTTP at `/mcp`, plain REST at
`/api/tools/<name>`, and health at `/livez`, `/readyz`, and `/health`.
For a shared HTTP deployment serving multiple mailboxes with per-request
Exchange credentials, see the [multi-tenant HTTP setup](docs/USAGE.md#multi-tenant-http-mode).

## What the assistant can do

- **Read fast** — `get_mailbox_overview` (morning brief in one call),
  `search_messages` (FTS over a local mirror, Arabic-correct, semantic
  mode optional), `get_message`, `get_thread`, `get_attachment`.
- **Calendar & people** — `list_events`, `get_event`,
  `check_availability`, `find_people`, `get_contact`.
- **Tasks & follow-ups** — `list_tasks`, `update_task`, `waiting_on`
  (sent threads nobody answered).
- **Write safely** — `create_draft` / `update_draft` (never send),
  labels, move; `send_draft` only exists at the `full` tier, behind a
  kill-switch, recipient allowlists, an hourly cap, and a two-phase
  **content-bound** confirmation that goes stale if the draft changes.
- **Operate** — `get_server_status` (connection, tier, cache watermarks —
  works even while Exchange is unreachable).

The complete, generated reference — every tool with its parameters,
envelope, error codes, and historical rename map — is
[`docs/API.md`](docs/API.md).

## MCP prompts

Beyond tools, the server exposes six ready-made prompts (`prompts/list` /
`prompts/get`, available over stdio and HTTP) that clients can offer as
slash commands: `morning-brief`, `health-check`, `draft-reply`,
`schedule-meeting`, `set-away-message`, and `send-draft-checklist`. Each
one chains a fixed sequence of the tools above and is tier-filtered the
same way tools are — a `read`-tier deployment only sees the two read-only
prompts. See [`docs/PROMPTS.md`](docs/PROMPTS.md) for the full reference.

## The safety model

| Mechanism | What it does |
|---|---|
| Capability tiers | `read` ⊂ `draft` ⊂ `full` — above-tier tools are not even registered |
| Kill-switch | `SEND_ENABLED=false` (default) refuses every send-class call |
| Recipient guards | Allow/deny globs on argument **and** draft-resolved recipients |
| Two-phase confirm | Preview + HMAC token bound to the draft's actual content; single-use |
| Rate cap | `EWS_MAX_SENDS_PER_HOUR` |
| Audit chain | Hash-chained log, verifier script, persists across restarts |

## Documentation

| | |
|---|---|
| [`docs/README.md`](docs/README.md) | Documentation map |
| [`docs/USAGE.md`](docs/USAGE.md) | Install & use: stdio, HTTP, Docker, configuration |
| [`docs/API.md`](docs/API.md) | API reference (generated from the registry) |
| [`docs/PROMPTS.md`](docs/PROMPTS.md) | The 6 MCP prompts (slash-command templates) and their tier filtering |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Architecture and rationale |
| [`examples/skills/exchange-assistant/`](examples/skills/exchange-assistant/) | Example assistant skill on top of the tool surface |
| [`examples/skills/exchange-inbox-triage/`](examples/skills/exchange-inbox-triage/) | Skill: morning brief, unread prioritization, follow-up tracking, read-tier hygiene |
| [`examples/skills/exchange-meeting-coordinator/`](examples/skills/exchange-meeting-coordinator/) | Skill: availability search, event create/update, two-phase meeting responses & cancellations |
| [`examples/skills/exchange-safe-mail/`](examples/skills/exchange-safe-mail/) | Skill: draft-first mail composition, content-bound send confirmation, out-of-office |

## Development

```bash
pip install -e '.[dev]'
python -m pytest -q                     # full suite — no Exchange needed
python -m ruff check .
python scripts/boot_smoke.py full       # end-to-end boot, dead endpoint
python scripts/dump_tool_table.py --check   # docs ↔ registry drift gate
```

CI: `tests` (blocking Ruff + tests on 3.11/3.12 + boot smokes + Docker
import smoke) runs on pushes and pull requests; `publish` builds
`ghcr.io/k9fr4n/ews-mcp` from tags `v1.*`, gated on the full test job. Each
release publishes its exact version tag plus the moving `v1` and `latest`
aliases. The workflow derives its image namespace from this GitHub repository.
After the first successful publication, set the GHCR package's visibility
to **Public** in the package settings if anonymous pulls are intended;
GitHub Actions does not change package visibility automatically.

## Repository layout

```
ewsmcp/        server package
tests/         unit and contract tests
scripts/       smoke, documentation, and operations utilities
docs/          usage, API, and architecture documentation
deploy/        deployment examples
examples/      example assistant skills
```

## Contributing & license

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT — see [LICENSE](LICENSE).
