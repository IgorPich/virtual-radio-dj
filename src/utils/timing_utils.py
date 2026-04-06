"""Small timing helpers used across modules."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator


@contextmanager
def timed(label: str = "") -> Generator[None, None, None]:
    """Context manager that prints elapsed seconds on exit (debug use)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"[timer] {label}: {elapsed:.3f}s")


def words_to_seconds(text: str, wpm: int = 140) -> float:
    """
    Estimate speech duration from word count.

    Args:
        text: Input text.
        wpm:  Words per minute (typical spoken speech ~140 WPM).

    Returns:
        Estimated duration in seconds.
    """
    word_count = len(text.split())
    return word_count / (wpm / 60.0)
