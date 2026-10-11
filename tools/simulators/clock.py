"""Clock abstractions for Aqua OS simulators and testing."""

import time
from datetime import datetime, timezone
from typing import Protocol


class IClock(Protocol):
    """Abstract clock protocol allowing virtual time injection."""

    def now(self) -> datetime:
        """Return current UTC timestamp."""
        ...

    def sleep(self, seconds: float) -> None:
        """Sleep or advance time."""
        ...


class SystemClock(IClock):
    """Real system wall-clock using OS time."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class VirtualClock(IClock):
    """Deterministic virtual clock for fast-forward testing and scenario reproduction."""

    def __init__(self, initial_time: datetime | None = None) -> None:
        if initial_time is None:
            self._current_time = datetime(2026, 10, 10, 6, 0, 0, tzinfo=timezone.utc)
        else:
            if initial_time.tzinfo is None:
                self._current_time = initial_time.replace(tzinfo=timezone.utc)
            else:
                self._current_time = initial_time.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._current_time

    def advance(self, seconds: float) -> None:
        """Advance virtual clock by seconds instantly."""
        from datetime import timedelta
        self._current_time += timedelta(seconds=seconds)

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

