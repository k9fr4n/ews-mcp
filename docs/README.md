# Documentation map

This repository contains the V5 server, published as version 4.5.x.

## V5 server (`v5/`, images `ghcr.io/k9fr4n/ews-mcp:v4.5*`)

| Document | What it covers |
|---|---|
| [`v5/README.md`](../v5/README.md) | Install & use: **stdio quick start (no Docker)** for Claude Code / Claude Desktop / any MCP client, HTTP transport, Docker, full configuration reference, the send flow, health endpoints |
| [`v5/docs/API.md`](../v5/docs/API.md) | **Full API reference, generated from the registry**: every tool with parameters, the canonical envelope, id aliases, error taxonomy, two-phase confirmation, cache freshness contract, historical rename map, intentionally-dropped list |
| [`v5/DESIGN.md`](../v5/DESIGN.md) | Architecture and rationale: dispatcher gate chain, alias store, cache mirror, body cleaning, audit chain |
| [`examples/skills/exchange-assistant/`](../examples/skills/exchange-assistant/) | Example assistant skill composed on top of the tool surface |
