"""MCP prompts: user-selected slash-command templates over the tool surface.

Prompts are a data-plane artifact like tools: a ``PromptSpec`` renders a
fixed instruction template with the caller's arguments interpolated. The
server never calls an LLM to build them (see docs/DESIGN.md §Tools, "the
law"). The calling assistant is the one that reads the template, chains the
named tools, and exercises judgment — the prompt just names the sequence
and hands the assistant a checklist so it does not skip a safety step
(e.g. draft-first, two-phase confirm, ``send_invitations: false`` by
default).

Tier-filtered exactly like ``ewsmcp.tools.build_registry``: a prompt that
recommends a tool above the deployment's ``EWS_CAPABILITY_TIER`` is not
listed, so a read-tier deployment never advertises a workflow it cannot
execute.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .tools.base import TIER_RANK

# --- argument model ---------------------------------------------------------


@dataclass(frozen=True)
class PromptArg:
    name: str
    description: str
    required: bool = False
    default: Optional[str] = None


@dataclass(frozen=True)
class PromptSpec:
    name: str
    title: str
    description: str
    min_tier: str  # read | draft | full — highest tier any tool it names requires
    arguments: List[PromptArg]
    render: Any  # Callable[[Dict[str, str]], str] -> the single user-message text

    def resolve(self, arguments: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Fill defaults, check required arguments, coerce to str."""
        provided = dict(arguments or {})
        resolved: Dict[str, str] = {}
        missing = []
        for arg in self.arguments:
            value = provided.get(arg.name)
            if value is None or value == "":
                if arg.required:
                    missing.append(arg.name)
                    continue
                value = arg.default or ""
            resolved[arg.name] = str(value)
        if missing:
            raise ValueError(
                f"Prompt '{self.name}' is missing required argument(s): {', '.join(missing)}"
            )
        return resolved


# --- templates ---------------------------------------------------------------


def _morning_brief(a: Dict[str, str]) -> str:
    return (
        f"Give me my morning brief for {a['timeframe']}:\n"
        "1. Call get_mailbox_overview and summarize unread mail by sender "
        "(most urgent first).\n"
        "2. List today's meetings, highlighting anything starting within "
        "the next hour.\n"
        "3. Call waiting_on and flag sent threads older than 3 days with no "
        "reply.\n"
        "4. Call list_tasks and only show tasks that are overdue or due "
        "today.\n"
        "Keep the whole summary to 5 lines or fewer, without quoting full "
        "message bodies."
    )


def _draft_reply(a: Dict[str, str]) -> str:
    key_points = a["key_points"] or "(no specific points provided)"
    return (
        f"Reply to message {a['message_id']} in a {a['tone']} tone.\n"
        '1. Call get_message with format: "full" to read the actual '
        "content before replying.\n"
        f"2. Weave in these points if relevant: {key_points}.\n"
        "3. Write the body yourself (the server never generates the "
        "text).\n"
        f'4. Call create_draft {{mode: "reply", reply_to: '
        f'"{a["message_id"]}", body: "..."}}.\n'
        "5. Do NOT call send_draft. Show the draft_id and preview, then "
        "wait for explicit confirmation before any sending step."
    )


def _send_draft_checklist(a: Dict[str, str]) -> str:
    return (
        f"I want to send draft {a['draft_id']}. Follow these steps in "
        "order, do not skip any:\n"
        f'1. Call send_draft {{draft_id: "{a["draft_id"]}"}} WITHOUT a '
        "confirm_token (phase 1).\n"
        "2. Show the real recipients, subject, and body excerpt returned "
        "in full — that is the server's ground truth, not your memory of "
        "the draft.\n"
        '3. Ask for explicit confirmation ("yes, send it") before '
        "continuing.\n"
        "4. Only after that confirmation, call send_draft again with the "
        "confirm_token you received.\n"
        "5. If the token is rejected (confirm_invalid), the draft changed "
        "in the meantime: go back to step 1, never force it."
    )


def _schedule_meeting(a: Dict[str, str]) -> str:
    title = a["title"] or "(no specific title)"
    return (
        f"Find a {a['duration_minutes']}-minute slot for {a['attendees']} "
        f"within {a['timeframe']}. Suggested title: {title}.\n"
        "1. Call check_availability {attendees: [...], start, end}.\n"
        "2. Propose 2 or 3 concrete slots, do not pick one yourself.\n"
        "3. Once a slot is confirmed by the user, call create_event with "
        "send_invitations: false by default.\n"
        "4. Only set send_invitations: true if the user explicitly asks "
        "for it — that triggers a real email to the attendees."
    )


def _set_away_message(a: Dict[str, str]) -> str:
    return (
        f"Set my out-of-office from {a['start']} to {a['end']} with this "
        f'message: "{a["message"]}".\n'
        "1. Call get_oof_settings to see the current state.\n"
        "2. Call set_oof with the period and message, using the same text "
        "for internal and external unless told otherwise.\n"
        "3. Confirm the final state (enabled/scheduled) returned by the "
        "server."
    )


def _health_check(a: Dict[str, str]) -> str:
    return (
        "Call get_server_status and summarize in 4 lines: Exchange "
        "connection state, active tier (read/draft/full), send kill-switch "
        "(enabled or not), and cache freshness (as_of)."
    )


# --- registry ------------------------------------------------------------

PROMPT_SPECS: List[PromptSpec] = [
    PromptSpec(
        name="morning-brief",
        title="Morning brief",
        description=("Summary of the mailbox, today's calendar, and pending follow-ups."),
        min_tier="read",
        arguments=[
            PromptArg(
                "timeframe",
                "Window to cover (e.g. today, tomorrow, +2d)",
                required=False,
                default="today",
            ),
        ],
        render=_morning_brief,
    ),
    PromptSpec(
        name="draft-reply",
        title="Draft a reply",
        description=("Prepares a reply to a specific message, without ever sending it."),
        min_tier="draft",
        arguments=[
            PromptArg("message_id", "Id or alias of the message (e.g. m12)", required=True),
            PromptArg(
                "tone",
                "Desired tone (formal, informal, neutral)",
                required=False,
                default="neutral",
            ),
            PromptArg(
                "key_points",
                "Key points to include, separated by ';'",
                required=False,
                default="",
            ),
        ],
        render=_draft_reply,
    ),
    PromptSpec(
        name="send-draft-checklist",
        title="Send a draft (two-phase confirm)",
        description=("Walks through the two-phase confirmation before actually sending a message."),
        min_tier="full",
        arguments=[
            PromptArg("draft_id", "Id of the draft (e.g. d1)", required=True),
        ],
        render=_send_draft_checklist,
    ),
    PromptSpec(
        name="schedule-meeting",
        title="Propose a meeting slot",
        description=(
            "Finds an available slot for a set of attendees and creates an "
            "event (no invitations by default)."
        ),
        min_tier="draft",
        arguments=[
            PromptArg("attendees", "Addresses separated by ';'", required=True),
            PromptArg("duration_minutes", "Duration in minutes", required=True),
            PromptArg(
                "timeframe",
                "Search window (e.g. +5d)",
                required=False,
                default="+5d",
            ),
            PromptArg("title", "Meeting title", required=False, default=""),
        ],
        render=_schedule_meeting,
    ),
    PromptSpec(
        name="set-away-message",
        title="Set the out-of-office message",
        description="Enables/schedules an automatic out-of-office reply.",
        min_tier="draft",
        arguments=[
            PromptArg("start", "Start date", required=True),
            PromptArg("end", "End date", required=True),
            PromptArg("message", "Out-of-office message text", required=True),
        ],
        render=_set_away_message,
    ),
    PromptSpec(
        name="health-check",
        title="EWS server health check",
        description=("Checks Exchange connection state, capability tier, and cache freshness."),
        min_tier="read",
        arguments=[],
        render=_health_check,
    ),
]


def build_prompt_registry(tier: str) -> Dict[str, PromptSpec]:
    """Tier-filter PROMPT_SPECS exactly like ``tools.build_registry``."""
    rank = TIER_RANK.get(tier, TIER_RANK["draft"])
    return {spec.name: spec for spec in PROMPT_SPECS if TIER_RANK[spec.min_tier] <= rank}
