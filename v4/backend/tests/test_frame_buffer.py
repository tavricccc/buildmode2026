"""BoundedRingBuffer tests."""

from __future__ import annotations

from v4.backend.adapters.frame_buffer import BoundedRingBuffer


def test_push_and_capacity() -> None:
    b: BoundedRingBuffer[int] = BoundedRingBuffer(max_items=3)
    for i in range(5):
        b.push(i)
    assert len(b) == 3
    assert b.snapshot() == [2, 3, 4]


def test_peek_latest_none_when_empty() -> None:
    b: BoundedRingBuffer[int] = BoundedRingBuffer(max_items=2)
    assert b.peek_latest() is None


def test_invalid_capacity() -> None:
    import pytest
    with pytest.raises(ValueError):
        BoundedRingBuffer(max_items=0)
