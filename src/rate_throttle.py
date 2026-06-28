"""
Fetch concurrency throttle (G5) — reduce parallel workers after rate-limit bursts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def is_rate_limit_error(error: str | None) -> bool:
    if not error:
        return False
    text = error.lower()
    return (
        "429" in text
        or "rate limit" in text
        or "too many requests" in text
        or "rate_limit" in text
    )


def count_rate_limit_errors(fetch_errors: list[dict]) -> int:
    return sum(1 for err in fetch_errors if is_rate_limit_error(err.get("error")))


@dataclass
class FetchThrottle:
    """Tracks per-run fetch concurrency; drops to 1 worker after rate-limit threshold."""

    max_workers: int | None = None
    throttled: bool = field(default=False, init=False)
    rate_limit_events: int = field(default=0, init=False)

    def effective_workers(self, source_count: int) -> int:
        if source_count <= 0:
            return 1
        if self.max_workers is not None:
            return max(1, min(self.max_workers, source_count))
        return source_count

    def observe_errors(self, fetch_errors: list[dict], *, threshold: int) -> bool:
        """Return True if throttle was activated this call."""
        hits = count_rate_limit_errors(fetch_errors)
        self.rate_limit_events += hits
        if hits >= threshold and not self.throttled:
            self.max_workers = 1
            self.throttled = True
            return True
        return False
