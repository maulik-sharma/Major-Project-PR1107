"""Consume a provider stream so that a user cancel takes effect immediately.

Adapters read sockets synchronously. A stalled provider (accepted the request,
then sent nothing) blocks that read until the read timeout, and closing the
socket from another thread does not wake it on Linux. So the engine reads the
adapter's iterator on a helper thread and waits on a queue, checking the cancel
event between polls; on cancel it returns at once and the helper thread ends on
its own when the read times out or the next chunk arrives.
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Iterator, Optional, TypeVar

T = TypeVar("T")

_DONE = object()


class _Raised:
    """Carries an exception from the helper thread to the consumer."""

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc


def iterate_cancellable(
    make_iterator: Callable[[], Iterator[T]],
    cancel_event: Optional[threading.Event],
    poll_seconds: float = 0.1,
) -> Iterator[T]:
    """Yield items from ``make_iterator()``; stop as soon as ``cancel_event`` is set.

    Exceptions raised by the iterator are re-raised in the caller's thread.
    Without a cancel event the iterator is consumed directly.
    """
    if cancel_event is None:
        yield from make_iterator()
        return

    items: "queue.Queue[object]" = queue.Queue()

    def pump() -> None:
        try:
            for item in make_iterator():
                items.put(item)
                if cancel_event.is_set():
                    break
        except BaseException as exc:  # forwarded to the consumer
            items.put(_Raised(exc))
        finally:
            items.put(_DONE)

    threading.Thread(target=pump, name="provider-stream", daemon=True).start()
    while True:
        if cancel_event.is_set():
            return
        try:
            item = items.get(timeout=poll_seconds)
        except queue.Empty:
            continue
        if item is _DONE:
            return
        if isinstance(item, _Raised):
            raise item.exc
        yield item  # type: ignore[misc]
