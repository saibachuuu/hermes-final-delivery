from __future__ import annotations

import unittest

from hermes_final_delivery.constants import TOOL_NAME
from hermes_final_delivery.state import DeliveryState

OWNER = ("default", "task-1", "session-1")


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _bound_state(*, clock=None) -> tuple[DeliveryState, str]:
    state = DeliveryState(clock=clock or Clock())
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:4",
            tool_name=TOOL_NAME,
        )
        is None
    )
    delivery_id = state.create(owner=OWNER, writer_model="writer/model")
    assert state.bind(
        delivery_id=delivery_id,
        owner=OWNER,
        turn_id="turn-1",
        source_api_request_id="turn-1:api:4",
        source_tool_call_id="call-final",
    )
    return state, delivery_id


def test_final_delivery_may_follow_tools_from_earlier_api_rounds() -> None:
    state = DeliveryState()
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:1",
            tool_name="terminal",
        )
        is None
    )
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:2",
            tool_name=TOOL_NAME,
        )
        is None
    )


def test_final_delivery_must_be_alone_in_its_api_batch() -> None:
    state = DeliveryState()
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:1",
            tool_name=TOOL_NAME,
        )
        is None
    )
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:1",
            tool_name="terminal",
        )
        is not None
    )

    other = DeliveryState()
    assert (
        other.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:1",
            tool_name="terminal",
        )
        is None
    )
    assert (
        other.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:1",
            tool_name=TOOL_NAME,
        )
        is not None
    )


def test_final_delivery_is_attempted_at_most_once_per_turn() -> None:
    state = DeliveryState()
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:1",
            tool_name=TOOL_NAME,
        )
        is None
    )
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:2",
            tool_name=TOOL_NAME,
        )
        is not None
    )


def test_bind_requires_matching_owner_and_reserved_batch() -> None:
    state = DeliveryState()
    delivery_id = state.create(owner=OWNER, writer_model="writer/model")
    assert not state.bind(
        delivery_id=delivery_id,
        owner=OWNER,
        turn_id="turn-1",
        source_api_request_id="turn-1:api:1",
        source_tool_call_id="call-final",
    )

    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:2",
            tool_name=TOOL_NAME,
        )
        is None
    )
    delivery_id = state.create(owner=OWNER, writer_model="writer/model")
    other_owner = ("default", "task-2", "session-2")
    assert not state.bind(
        delivery_id=delivery_id,
        owner=other_owner,
        turn_id="turn-1",
        source_api_request_id="turn-1:api:2",
        source_tool_call_id="call-final",
    )


def test_route_is_replayed_only_for_the_same_logical_request() -> None:
    state, delivery_id = _bound_state()
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:4",
        )
        is None
    )

    first = state.route(
        owner=OWNER,
        turn_id="turn-1",
        api_request_id="turn-1:api:5",
    )
    retry = state.route(
        owner=OWNER,
        turn_id="turn-1",
        api_request_id="turn-1:api:5",
    )
    assert first is not None
    assert first == retry
    assert first.delivery_id == delivery_id
    assert first.writer_model == "writer/model"

    assert (
        state.complete_response(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
            assistant_tool_call_count=0,
        )
        == "consumed"
    )
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:6",
        )
        is None
    )


def test_writer_tool_call_is_blocked_then_default_route_takes_over() -> None:
    state, _ = _bound_state()
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
        )
        is not None
    )
    assert (
        state.complete_response(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
            assistant_tool_call_count=1,
        )
        == "takeover"
    )
    assert (
        state.reserve_tool_call(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
            tool_name="terminal",
        )
        is not None
    )
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:6",
        )
        is None
    )
    assert state.snapshot()["active"] == 0


def test_writer_error_disarms_before_a_retry() -> None:
    state, _ = _bound_state()
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
        )
        is not None
    )
    assert state.disarm_error(
        owner=OWNER,
        turn_id="turn-1",
        api_request_id="turn-1:api:5",
    )
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
        )
        is None
    )


def test_expired_handoffs_fail_open() -> None:
    clock = Clock()
    state, _ = _bound_state(clock=clock)
    clock.now += 301
    assert (
        state.route(
            owner=OWNER,
            turn_id="turn-1",
            api_request_id="turn-1:api:5",
        )
        is None
    )
    assert state.snapshot()["active"] == 0


def test_turn_cleanup_removes_active_and_attempt_records() -> None:
    state, _ = _bound_state()
    state.end_turn(owner=OWNER, turn_id="turn-1")
    assert state.snapshot() == {
        "created": 0,
        "active": 0,
        "attempted": 0,
        "batches": 0,
    }


def load_tests(loader, tests, pattern):  # noqa: ARG001
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite
