"""Thread-safe, content-free state for a one-request model-routing lease."""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal, TypeAlias

from .constants import (
    AFTER_HANDOFF_BLOCK_MESSAGE,
    ISOLATION_BLOCK_MESSAGE,
    TOOL_NAME,
)

Owner: TypeAlias = tuple[str, str, str]
TurnKey: TypeAlias = tuple[Owner, str]
BatchKey: TypeAlias = tuple[Owner, str, str]
Phase: TypeAlias = Literal["armed", "routing", "takeover"]


@dataclass(slots=True)
class CreatedHandoff:
    delivery_id: str
    owner: Owner
    created_at: float


@dataclass(slots=True)
class ActiveHandoff:
    delivery_id: str
    owner: Owner
    turn_id: str
    source_api_request_id: str
    source_tool_call_id: str
    created_at: float
    updated_at: float
    phase: Phase = "armed"
    target_api_request_id: str | None = None
    routed_model: str | None = None


@dataclass(slots=True)
class BatchGate:
    updated_at: float
    saw_final_delivery: bool = False
    saw_other_tool: bool = False


@dataclass(frozen=True, slots=True)
class RouteLease:
    delivery_id: str
    writer_model: str


class DeliveryState:
    """Keep routing identity without retaining drafts, messages, or provider payloads."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        capacity: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        self._capacity = max(16, int(capacity))
        self._clock = clock
        self._lock = threading.Lock()
        self._created: dict[str, CreatedHandoff] = {}
        self._active: dict[TurnKey, ActiveHandoff] = {}
        self._attempted: dict[TurnKey, float] = {}
        self._batches: dict[BatchKey, BatchGate] = {}

    def reserve_tool_call(
        self,
        *,
        owner: Owner,
        turn_id: str,
        api_request_id: str,
        tool_name: str,
    ) -> str | None:
        """Return a block reason, or reserve this tool call atomically."""
        if not turn_id or not api_request_id:
            return ISOLATION_BLOCK_MESSAGE if tool_name == TOOL_NAME else None

        now = self._clock()
        turn_key = (owner, turn_id)
        batch_key = (owner, turn_id, api_request_id)
        with self._lock:
            self._cleanup_locked(now)

            if turn_key in self._active:
                return AFTER_HANDOFF_BLOCK_MESSAGE

            gate = self._batches.get(batch_key)
            if gate is None:
                gate = BatchGate(updated_at=now)
                self._batches[batch_key] = gate
            gate.updated_at = now

            if tool_name == TOOL_NAME:
                if (
                    turn_key in self._attempted
                    or gate.saw_final_delivery
                    or gate.saw_other_tool
                ):
                    return ISOLATION_BLOCK_MESSAGE
                gate.saw_final_delivery = True
                self._attempted[turn_key] = now
            else:
                if gate.saw_final_delivery:
                    return AFTER_HANDOFF_BLOCK_MESSAGE
                gate.saw_other_tool = True

            self._trim_locked()
            return None

    def create(self, *, owner: Owner) -> str:
        """Create an opaque handoff record. The draft deliberately is not accepted."""
        now = self._clock()
        delivery_id = f"fd_{secrets.token_urlsafe(12)}"
        with self._lock:
            self._cleanup_locked(now)
            self._created[delivery_id] = CreatedHandoff(
                delivery_id=delivery_id,
                owner=owner,
                created_at=now,
            )
            self._trim_locked()
        return delivery_id

    def bind(
        self,
        *,
        delivery_id: str,
        owner: Owner,
        turn_id: str,
        source_api_request_id: str,
        source_tool_call_id: str,
    ) -> bool:
        """Bind a successful handler result to the outer hook's trusted identity."""
        if (
            not delivery_id
            or not turn_id
            or not source_api_request_id
            or not source_tool_call_id
        ):
            return False

        now = self._clock()
        turn_key = (owner, turn_id)
        with self._lock:
            self._cleanup_locked(now)
            created = self._created.pop(delivery_id, None)
            batch = self._batches.get((owner, turn_id, source_api_request_id))
            if (
                created is None
                or created.owner != owner
                or turn_key in self._active
                or turn_key not in self._attempted
                or batch is None
                or not batch.saw_final_delivery
            ):
                return False
            self._active[turn_key] = ActiveHandoff(
                delivery_id=delivery_id,
                owner=owner,
                turn_id=turn_id,
                source_api_request_id=source_api_request_id,
                source_tool_call_id=source_tool_call_id,
                created_at=created.created_at,
                updated_at=now,
            )
            self._trim_locked()
            return True

    def route(
        self,
        *,
        owner: Owner,
        turn_id: str,
        api_request_id: str,
        writer_model: str | None,
    ) -> RouteLease | None:
        """Acquire or replay the lease for exactly one logical provider request."""
        if not turn_id or not api_request_id:
            return None

        now = self._clock()
        turn_key = (owner, turn_id)
        with self._lock:
            self._cleanup_locked(now)
            active = self._active.get(turn_key)
            if active is None:
                return None

            if active.phase == "armed":
                if api_request_id == active.source_api_request_id:
                    return None
                selected_model = str(writer_model or "").strip()
                if not selected_model:
                    self._active.pop(turn_key, None)
                    return None
                active.phase = "routing"
                active.target_api_request_id = api_request_id
                active.routed_model = selected_model
                active.updated_at = now
            elif active.phase == "routing":
                if api_request_id != active.target_api_request_id:
                    self._active.pop(turn_key, None)
                    return None
                active.updated_at = now
            else:  # takeover: the writer tried a tool; every subsequent request uses the default route.
                if api_request_id != active.target_api_request_id:
                    self._active.pop(turn_key, None)
                return None

            if not active.routed_model:
                self._active.pop(turn_key, None)
                return None
            return RouteLease(
                delivery_id=active.delivery_id,
                writer_model=active.routed_model,
            )

    def complete_response(
        self,
        *,
        owner: Owner,
        turn_id: str,
        api_request_id: str,
        assistant_tool_call_count: int,
    ) -> Literal["consumed", "takeover"] | None:
        """Consume a normal writer response, or arm default-model takeover for tool output."""
        now = self._clock()
        turn_key = (owner, turn_id)
        with self._lock:
            self._cleanup_locked(now)
            active = self._active.get(turn_key)
            if (
                active is None
                or active.phase != "routing"
                or active.target_api_request_id != api_request_id
            ):
                return None
            if assistant_tool_call_count > 0:
                active.phase = "takeover"
                active.updated_at = now
                return "takeover"
            self._active.pop(turn_key, None)
            return "consumed"

    def disarm_error(self, *, owner: Owner, turn_id: str, api_request_id: str) -> bool:
        """Fail open: a retry of a failed writer request uses the normal model."""
        now = self._clock()
        turn_key = (owner, turn_id)
        with self._lock:
            self._cleanup_locked(now)
            active = self._active.get(turn_key)
            if active is None or active.target_api_request_id != api_request_id:
                return False
            self._active.pop(turn_key, None)
            return True

    def end_turn(self, *, owner: Owner, turn_id: str | None = None) -> None:
        """Discard all ephemeral records owned by a completed turn/session."""
        with self._lock:
            if turn_id:
                turn_key = (owner, turn_id)
                self._active.pop(turn_key, None)
                self._attempted.pop(turn_key, None)
                self._batches = {
                    key: value
                    for key, value in self._batches.items()
                    if not (key[0] == owner and key[1] == turn_id)
                }
            else:
                self._active = {
                    key: value for key, value in self._active.items() if key[0] != owner
                }
                self._attempted = {
                    key: value
                    for key, value in self._attempted.items()
                    if key[0] != owner
                }
                self._batches = {
                    key: value
                    for key, value in self._batches.items()
                    if key[0] != owner
                }
            self._created = {
                key: value
                for key, value in self._created.items()
                if value.owner != owner
            }

    def clear(self) -> None:
        with self._lock:
            self._created.clear()
            self._active.clear()
            self._attempted.clear()
            self._batches.clear()

    def snapshot(self) -> dict[str, int]:
        """Content-free counts used by tests and diagnostics."""
        with self._lock:
            self._cleanup_locked(self._clock())
            return {
                "created": len(self._created),
                "active": len(self._active),
                "attempted": len(self._attempted),
                "batches": len(self._batches),
            }

    def _cleanup_locked(self, now: float) -> None:
        cutoff = now - self._ttl_seconds
        self._created = {
            key: value
            for key, value in self._created.items()
            if value.created_at >= cutoff
        }
        self._active = {
            key: value
            for key, value in self._active.items()
            if value.updated_at >= cutoff
        }
        self._attempted = {
            key: value for key, value in self._attempted.items() if value >= cutoff
        }
        self._batches = {
            key: value
            for key, value in self._batches.items()
            if value.updated_at >= cutoff
        }

    def _trim_locked(self) -> None:
        self._trim_mapping(self._created, lambda item: item[1].created_at)
        self._trim_mapping(self._active, lambda item: item[1].updated_at)
        self._trim_mapping(self._attempted, lambda item: item[1])
        self._trim_mapping(self._batches, lambda item: item[1].updated_at)

    def _trim_mapping(self, mapping: dict, timestamp: Callable[[tuple], float]) -> None:
        overflow = len(mapping) - self._capacity
        if overflow <= 0:
            return
        for key, _ in sorted(mapping.items(), key=timestamp)[:overflow]:
            mapping.pop(key, None)
