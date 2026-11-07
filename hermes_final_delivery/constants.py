"""Public tool copy and protocol constants."""

from __future__ import annotations

PLUGIN_ID = "hermes-final-delivery"
TOOL_NAME = "final_delivery"
TOOLSET = "final_delivery"

TOOL_DESCRIPTION = (
    "Hand off a completed, substantial task's final user-facing reply to the configured "
    "delivery model. Use ONLY after all requested work is complete and verified, no tools "
    "or decisions remain, and a polished handoff would materially help. Call this tool "
    "alone, as the last tool call, at most once. Do not use it for short or routine answers, "
    "progress updates, questions, refusals, or merely because you are about to stop; reply "
    "normally instead. Put a complete, fact-grounded final answer in `draft`: the outcome, "
    "relevant files or commands, verification results, caveats, and unresolved items. "
    "Exclude hidden reasoning, secrets, credentials, and raw tool output. The delivery model "
    "may improve structure, clarity, tone, and concision, but cannot do more work or invent "
    "facts. After calling, do not continue or call another tool; the next assistant response "
    "is the final delivery."
)

DRAFT_DESCRIPTION = (
    "A complete, user-ready final answer in the user's language. It must be safe to send "
    "unchanged and contain every verified fact the user needs: outcome, changed files, "
    "commands or tests run, caveats, and unresolved items. Omit hidden reasoning, secrets, "
    "credentials, and raw tool output."
)

HANDOFF_INSTRUCTION = (
    "You are handling a one-response final-delivery handoff. Write the final user-facing "
    "reply now from the `draft` in the immediately preceding `final_delivery` call and treat "
    "it as authoritative. Preserve every concrete fact, path, command, number, test result, "
    "caveat, and unresolved item. Improve only organization, clarity, tone, and concision; "
    "match the user's language. Do not perform more work, call or describe tools, ask a "
    "follow-up question, mention this handoff, or add claims. Output only the final reply."
)

TOOL_SCHEMA = {
    "name": TOOL_NAME,
    "description": TOOL_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "draft": {
                "type": "string",
                "description": DRAFT_DESCRIPTION,
            }
        },
        "required": ["draft"],
        "additionalProperties": False,
    },
}

TOOL_REQUEST_KEYS = (
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "functions",
    "function_call",
    "toolConfig",
    "tool_config",
)

NOT_ARMED_MESSAGE = (
    "Final-delivery handoff was not armed. Continue by sending the submitted draft yourself. "
    "Do not call final_delivery again this turn."
)

ISOLATION_BLOCK_MESSAGE = (
    "final_delivery must be called alone in its tool-call batch and at most once per turn. "
    "Send the prepared draft directly and do not call final_delivery again this turn."
)

AFTER_HANDOFF_BLOCK_MESSAGE = (
    "This tool call was blocked because final_delivery must be the last tool call. "
    "Return the prepared final answer now without using tools."
)
