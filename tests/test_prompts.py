"""MCP prompts: tier filtering, argument resolution, wiring into the server."""

import asyncio

import pytest
from conftest import make_settings

from ewsmcp.prompts import PROMPT_SPECS, build_prompt_registry
from ewsmcp.server import build_context, build_mcp_server


def test_six_prompts_defined():
    assert len(PROMPT_SPECS) == 6
    assert len({s.name for s in PROMPT_SPECS}) == 6  # no duplicate names


def test_tier_filtering_matches_named_tools():
    # read tier: only prompts whose every named tool is itself read-tier.
    read = build_prompt_registry("read")
    assert set(read) == {"morning-brief", "health-check"}

    draft = build_prompt_registry("draft")
    assert set(draft) == {
        "morning-brief",
        "health-check",
        "draft-reply",
        "schedule-meeting",
        "set-away-message",
    }

    full = build_prompt_registry("full")
    assert set(full) == set(build_prompt_registry("draft")) | {"send-draft-checklist"}


def test_resolve_fills_defaults_and_validates_required():
    spec = build_prompt_registry("full")["draft-reply"]
    resolved = spec.resolve({"message_id": "m12"})
    assert resolved["tone"] == "neutral"
    assert resolved["key_points"] == ""

    with pytest.raises(ValueError):
        spec.resolve({})  # message_id is required


def test_render_produces_nonempty_text_for_every_prompt():
    for spec in PROMPT_SPECS:
        args = {a.name: (a.default or "x") for a in spec.arguments if not a.required}
        args.update({a.name: "x" for a in spec.arguments if a.required})
        resolved = spec.resolve(args)
        text = spec.render(resolved)
        assert isinstance(text, str) and text.strip()


def test_server_exposes_prompts_capability_and_list(tmp_path):
    import mcp.types as t

    ctx = build_context(make_settings(ews_capability_tier="full"))
    server = build_mcp_server(ctx)

    caps = server.get_capabilities(
        notification_options=__import__(
            "mcp.server.lowlevel.server", fromlist=["NotificationOptions"]
        ).NotificationOptions(),
        experimental_capabilities={},
    )
    assert caps.prompts is not None

    handler = server.request_handlers[t.ListPromptsRequest]
    result = asyncio.run(handler(t.ListPromptsRequest(method="prompts/list")))
    names = {p.name for p in result.root.prompts}
    assert names == set(build_prompt_registry("full"))


def test_get_prompt_unknown_name_raises(tmp_path):
    import mcp.types as t

    ctx = build_context(make_settings(ews_capability_tier="full"))
    server = build_mcp_server(ctx)
    handler = server.request_handlers[t.GetPromptRequest]
    req = t.GetPromptRequest(
        method="prompts/get",
        params=t.GetPromptRequestParams(name="does-not-exist", arguments={}),
    )
    with pytest.raises(ValueError):
        asyncio.run(handler(req))


def test_get_prompt_missing_required_argument_raises(tmp_path):
    import mcp.types as t

    ctx = build_context(make_settings(ews_capability_tier="full"))
    server = build_mcp_server(ctx)
    handler = server.request_handlers[t.GetPromptRequest]
    req = t.GetPromptRequest(
        method="prompts/get",
        params=t.GetPromptRequestParams(name="draft-reply", arguments={}),
    )
    with pytest.raises(ValueError):
        asyncio.run(handler(req))
