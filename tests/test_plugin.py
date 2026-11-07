from __future__ import annotations

import json
import unittest
from typing import Any

from hermes_final_delivery.constants import TOOL_NAME, TOOL_REQUEST_KEYS
from hermes_final_delivery.plugin import register


class FakeContext:
    profile_name = "default"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})
        self.tools: dict[str, Any] = {}
        self.hooks: dict[str, Any] = {}
        self.middleware: dict[str, Any] = {}
        self.commands: dict[str, Any] = {}
        self.cli_commands: dict[str, Any] = {}
        self.unload_callbacks: list[Any] = []

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        self.config[key] = value

    def register_tool(self, name: str, **kwargs: Any) -> None:
        self.tools[name] = kwargs

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks[name] = callback

    def register_middleware(self, name: str, callback: Any) -> None:
        self.middleware[name] = callback

    def register_command(self, name: str, **kwargs: Any) -> None:
        self.commands[name] = kwargs

    def register_cli_command(self, name: str, **kwargs: Any) -> None:
        self.cli_commands[name] = kwargs

    def on_unload(self, callback: Any) -> None:
        self.unload_callbacks.append(callback)


def _context(config: dict[str, Any] | None = None) -> FakeContext:
    ctx = FakeContext(config)
    register(ctx)
    return ctx


def _arm(ctx: FakeContext) -> tuple[str, dict[str, Any]]:
    identity = {
        "task_id": "task-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "api_request_id": "turn-1:api:4",
    }
    assert ctx.hooks["pre_tool_call"](tool_name=TOOL_NAME, **identity) is None
    result = ctx.tools[TOOL_NAME]["handler"](
        {"draft": "All work is complete and the tests pass."},
        task_id=identity["task_id"],
        session_id=identity["session_id"],
    )
    payload = json.loads(result)
    assert payload["success"] is True
    ctx.hooks["post_tool_call"](
        tool_name=TOOL_NAME,
        result=result,
        status="ok",
        tool_call_id="call-final",
        **identity,
    )
    return result, identity


def test_registers_declared_components() -> None:
    ctx = _context()
    assert set(ctx.tools) == {"final_delivery"}
    assert set(ctx.hooks) == {
        "pre_tool_call",
        "post_tool_call",
        "post_api_request",
        "api_request_error",
        "on_session_end",
    }
    assert set(ctx.middleware) == {"llm_request"}
    assert set(ctx.commands) == {"final-delivery-model"}
    assert set(ctx.cli_commands) == {"final-delivery-model"}
    assert len(ctx.unload_callbacks) == 1


def test_missing_writer_model_fails_open_with_a_tool_error() -> None:
    ctx = _context()
    result = ctx.tools[TOOL_NAME]["handler"](
        {"draft": "Ready to send."},
        task_id="task-1",
        session_id="session-1",
    )
    assert "not armed" in json.loads(result)["error"]


def test_invalid_or_oversized_drafts_do_not_arm() -> None:
    ctx = _context({"writer_model": "writer/model", "max_draft_chars": 1000})
    handler = ctx.tools[TOOL_NAME]["handler"]
    assert "non-empty" in json.loads(handler({"draft": "   "}))["error"]
    assert "exceeds 1000" in json.loads(handler({"draft": "x" * 1001}))["error"]


def test_handoff_rewrites_one_request_and_strips_tool_controls() -> None:
    ctx = _context({"writer_model": "writer/model"})
    _, identity = _arm(ctx)
    target = {**identity, "api_request_id": "turn-1:api:5"}
    request = {
        "model": "default/model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "tools": [{"type": "function"}],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "functions": [],
        "function_call": "auto",
        "toolConfig": {},
        "tool_config": {},
    }
    outcome = ctx.middleware["llm_request"](request=request, **target)
    assert outcome is not None
    routed = outcome["request"]
    assert routed["model"] == "writer/model"
    assert routed["messages"] is request["messages"]
    assert routed["stream"] is True
    assert all(key not in routed for key in TOOL_REQUEST_KEYS)
    assert request["model"] == "default/model"
    assert "tools" in request

    retry = ctx.middleware["llm_request"](request=request, **target)
    assert retry is not None
    assert retry["request"]["model"] == "writer/model"

    ctx.hooks["post_api_request"](assistant_tool_call_count=0, **target)
    later = ctx.middleware["llm_request"](
        request=request,
        **{**identity, "api_request_id": "turn-1:api:6"},
    )
    assert later is None


def test_provider_specific_model_wins_over_fallback() -> None:
    ctx = _context(
        {
            "writer_models": {"OpenRouter": "writer/openrouter"},
            "writer_model": "writer/fallback",
        }
    )
    _, identity = _arm(ctx)
    outcome = ctx.middleware["llm_request"](
        request={"model": "default/model"},
        provider="OPENROUTER",
        **{**identity, "api_request_id": "turn-1:api:5"},
    )
    assert outcome is not None
    assert outcome["request"]["model"] == "writer/openrouter"


def test_unmapped_provider_without_fallback_uses_default_route() -> None:
    ctx = _context({"writer_models": {"openrouter": "writer/openrouter"}})
    _, identity = _arm(ctx)
    target = {**identity, "api_request_id": "turn-1:api:5"}
    assert (
        ctx.middleware["llm_request"](
            request={"model": "default/model"},
            provider="anthropic",
            **target,
        )
        is None
    )


def test_writer_tool_call_is_blocked_and_next_request_uses_default() -> None:
    ctx = _context({"writer_model": "writer/model"})
    _, identity = _arm(ctx)
    target = {**identity, "api_request_id": "turn-1:api:5"}
    request = {"model": "default/model", "tools": [{"type": "function"}]}
    assert ctx.middleware["llm_request"](request=request, **target) is not None
    ctx.hooks["post_api_request"](assistant_tool_call_count=1, **target)

    blocked = ctx.hooks["pre_tool_call"](tool_name="terminal", **target)
    assert blocked is not None
    assert blocked["action"] == "block"

    next_request = {**identity, "api_request_id": "turn-1:api:6"}
    assert ctx.middleware["llm_request"](request=request, **next_request) is None


def test_writer_error_makes_same_request_retry_use_default() -> None:
    ctx = _context({"writer_model": "writer/model"})
    _, identity = _arm(ctx)
    target = {**identity, "api_request_id": "turn-1:api:5"}
    request = {"model": "default/model"}
    assert ctx.middleware["llm_request"](request=request, **target) is not None
    ctx.hooks["api_request_error"](**target)
    assert ctx.middleware["llm_request"](request=request, **target) is None


def load_tests(loader, tests, pattern):  # noqa: ARG001
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite
