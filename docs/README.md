# Documentation map

This repository contains one server implementation, published as version 1.0.0.

## Server (`ghcr.io/k9fr4n/ews-mcp:v1.0.0`)

| Document | What it covers |
|---|---|
| [`USAGE.md`](USAGE.md) | Install & use: **stdio quick start (no Docker)** for Claude Code / Claude Desktop / any MCP client, HTTP transport, Docker, full configuration reference, the send flow, health endpoints |
| [`API.md`](API.md) | **Full API reference, generated from the registry**: every tool with parameters, the canonical envelope, id aliases, error taxonomy, two-phase confirmation, cache freshness contract, historical rename map, intentionally-dropped list |
| [`DESIGN.md`](DESIGN.md) | Architecture and rationale: dispatcher gate chain, alias store, cache mirror, body cleaning, audit chain |
| [`examples/skills/exchange-assistant/`](../examples/skills/exchange-assistant/) | Example assistant skill composed on top of the tool surface |
