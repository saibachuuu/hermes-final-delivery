"""Hermes registration and callback adapters."""

from __future__ import annotations

import json
from typing import Any

from .commands import COMMAND_DESCRIPTION, COMMAND_NAME, DeliveryModelCommands
from .constants import (
    HANDOFF_INSTRUCTION,
    NOT_ARMED_MESSAGE,
    PLUGIN_ID,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    TOOL_REQUEST_KEYS,
    TOOL_SCHEMA,
    TOOLSET,
)
from .model_config import WriterModelConfig
from .state import DeliveryState, Owner

DEFAULT_MAX_DRAFT_CHARS = 20_000
DEFAULT_TTL_SECONDS = 300


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _json_result(**values: Any) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _delivery_id_from_result(result: Any) -> str | None:
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    delivery_id = payload.get("delivery_id")
    if (
        payload.get("success") is True
        and payload.get("status") == "final_delivery_armed"
        and isinstance(delivery_id, str)
        and delivery_id.startswith("fd_")
    ):
        return delivery_id
    return None


class FinalDeliveryPlugin:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.profile_name = str(getattr(ctx, "profile_name", "default") or "default")
        ttl = _bounded_int(
            ctx.get_config("pending_ttl_seconds", DEFAULT_TTL_SECONDS),
            default=DEFAULT_TTL_SECONDS,
            minimum=30,
            maximum=3600,
        )
        self.state = DeliveryState(ttl_seconds=ttl)
        self.model_config = WriterModelConfig(ctx)

    def owner(self, *, task_id: Any = None, session_id: Any = None) -> Owner:
        return (
            self.profile_name,
            str(task_id or ""),
            str(session_id or ""),
        )

    def handle_final_delivery(
        self,
        args: dict[str, Any],
        *,
        task_id: Any = None,
        session_id: Any = None,
        **_: Any,
    ) -> str:
        if not self.model_config.has_any():
            return _json_result(error=NOT_ARMED_MESSAGE)

        draft = args.get("draft") if isinstance(args, dict) else None
        if not isinstance(draft, str) or not draft.strip():
            return _json_result(
                error=(
                    "Final-delivery handoff was not armed because draft must be a non-empty "
                    "string. Send the draft yourself and do not call final_delivery again this turn."
                )
            )

        max_chars = _bounded_int(
            self.ctx.get_config("max_draft_chars", DEFAULT_MAX_DRAFT_CHARS),
            default=DEFAULT_MAX_DRAFT_CHARS,
            minimum=1000,
            maximum=100_000,
        )
        if len(draft) > max_chars:
            return _json_result(
                error=(
                    f"Final-delivery handoff was not armed because draft exceeds {max_chars} "
                    "characters. Send a concise version yourself and do not call final_delivery "
                    "again this turn."
                )
            )

        delivery_id = self.state.create(
            owner=self.owner(task_id=task_id, session_id=session_id)
        )
        return _json_result(
            success=True,
            status="final_delivery_armed",
            delivery_id=delivery_id,
            instruction=HANDOFF_INSTRUCTION,
        )

    def pre_tool_call(
        self,
        *,
        tool_name: Any = None,
        task_id: Any = None,
        session_id: Any = None,
        turn_id: Any = None,
        api_request_id: Any = None,
        **_: Any,
    ) -> dict[str, str] | None:
        name = str(tool_name or "")
        reason = self.state.reserve_tool_call(
            owner=self.owner(task_id=task_id, session_id=session_id),
            turn_id=str(turn_id or ""),
            api_request_id=str(api_request_id or ""),
            tool_name=name,
        )
        if reason:
            return {"action": "block", "message": reason}
        return None

    def post_tool_call(
        self,
        *,
        tool_name: Any = None,
        result: Any = None,
        status: Any = None,
        task_id: Any = None,
        session_id: Any = None,
        turn_id: Any = None,
        api_request_id: Any = None,
        tool_call_id: Any = None,
        **_: Any,
    ) -> None:
        if str(tool_name or "") != TOOL_NAME or str(status or "ok") != "ok":
            return
        delivery_id = _delivery_id_from_result(result)
        if delivery_id is None:
            return
        self.state.bind(
            delivery_id=delivery_id,
            owner=self.owner(task_id=task_id, session_id=session_id),
            turn_id=str(turn_id or ""),
            source_api_request_id=str(api_request_id or ""),
            source_tool_call_id=str(tool_call_id or ""),
        )

    def llm_request(
        self,
        *,
        request: Any = None,
        task_id: Any = None,
        session_id: Any = None,
        turn_id: Any = None,
        api_request_id: Any = None,
        provider: Any = None,
        **_: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            return None
        lease = self.state.route(
            owner=self.owner(task_id=task_id, session_id=session_id),
            turn_id=str(turn_id or ""),
            api_request_id=str(api_request_id or ""),
            writer_model=self.model_config.resolve(provider),
        )
        if lease is None:
            return None

        routed = dict(request)
        routed["model"] = lease.writer_model
        for key in TOOL_REQUEST_KEYS:
            routed.pop(key, None)
        return {
            "request": routed,
            "source": PLUGIN_ID,
            "reason": "one-response final-delivery handoff",
        }

    def post_api_request(
        self,
        *,
        task_id: Any = None,
        session_id: Any = None,
        turn_id: Any = None,
        api_request_id: Any = None,
        assistant_tool_call_count: Any = 0,
        **_: Any,
    ) -> None:
        count = _bounded_int(
            assistant_tool_call_count,
            default=0,
            minimum=0,
            maximum=1_000_000,
        )
        self.state.complete_response(
            owner=self.owner(task_id=task_id, session_id=session_id),
            turn_id=str(turn_id or ""),
            api_request_id=str(api_request_id or ""),
            assistant_tool_call_count=count,
        )

    def api_request_error(
        self,
        *,
        task_id: Any = None,
        session_id: Any = None,
        turn_id: Any = None,
        api_request_id: Any = None,
        **_: Any,
    ) -> None:
        self.state.disarm_error(
            owner=self.owner(task_id=task_id, session_id=session_id),
            turn_id=str(turn_id or ""),
            api_request_id=str(api_request_id or ""),
        )

    def on_session_end(
        self,
        *,
        task_id: Any = None,
        session_id: Any = None,
        turn_id: Any = None,
        **_: Any,
    ) -> None:
        self.state.end_turn(
            owner=self.owner(task_id=task_id, session_id=session_id),
            turn_id=str(turn_id) if turn_id else None,
        )


def register(ctx: Any) -> None:
    """Register the tool, guard hooks, and one-request routing middleware."""
    plugin = FinalDeliveryPlugin(ctx)
    commands = DeliveryModelCommands(plugin.model_config)
    ctx.register_tool(
        name=TOOL_NAME,
        toolset=TOOLSET,
        schema=TOOL_SCHEMA,
        handler=plugin.handle_final_delivery,
        description=TOOL_DESCRIPTION,
        emoji="✍️",
    )
    ctx.register_hook("pre_tool_call", plugin.pre_tool_call)
    ctx.register_hook("post_tool_call", plugin.post_tool_call)
    ctx.register_hook("post_api_request", plugin.post_api_request)
    ctx.register_hook("api_request_error", plugin.api_request_error)
    ctx.register_hook("on_session_end", plugin.on_session_end)
    ctx.register_middleware("llm_request", plugin.llm_request)
    ctx.register_command(
        COMMAND_NAME,
        handler=commands.handle_slash,
        description=COMMAND_DESCRIPTION,
        args_hint="[list|set <provider> <model>|unset <provider>|default <model>|clear-default]",
        argument_mode="text",
    )
    ctx.register_cli_command(
        name=COMMAND_NAME,
        help=COMMAND_DESCRIPTION,
        setup_fn=commands.setup_cli,
        handler_fn=commands.handle_cli,
        description=(
            "Manage provider-specific models used for the one-response final-delivery handoff."
        ),
    )
    ctx.on_unload(plugin.state.clear)
