from __future__ import annotations

from copy import deepcopy


class DeterministicTelemetryReplay:
    def __init__(self, events: list[dict[str, object]]) -> None:
        self._events = [deepcopy(event) for event in events]
        self._index = 0

    def next_event(self) -> dict[str, object] | None:
        if self._index >= len(self._events):
            return None
        event = deepcopy(self._events[self._index])
        self._index += 1
        return event

    def reset(self) -> None:
        self._index = 0

    def remaining(self) -> int:
        return len(self._events) - self._index

    def total(self) -> int:
        return len(self._events)

    def consumed(self) -> int:
        return self._index
