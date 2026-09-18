from queue import Full, Queue
from threading import Event, Thread, current_thread
from typing import Any, Callable, Dict, Optional, TypeVar

from loguru import logger
from reactivex import Observable, abc
from reactivex.disposable import Disposable, SerialDisposable

_T = TypeVar('_T')


def observe_on_new_thread(
    queue_size: Optional[int] = None,
    thread_name: Optional[str] = None,
    logger_context: Optional[Dict[str, Any]] = None,
) -> Callable[[Observable[_T]], Observable[_T]]:
    def observe_on(source: Observable[_T]) -> Observable[_T]:
        def subscribe(
            observer: abc.ObserverBase[_T],
            scheduler: Optional[abc.SchedulerBase] = None,
        ) -> abc.DisposableBase:
            disposed = Event()
            subscription = SerialDisposable()
            queue: Queue[Callable[..., Any]] = Queue(maxsize=queue_size or 0)

            def run() -> None:
                try:
                    with logger.contextualize(**(logger_context or {})):
                        while not disposed.is_set():
                            queue.get()()
                finally:
                    dispose()

            def enqueue(callback: Callable[[], Any]) -> None:
                # Retain backpressure, but let blocked producers notice shutdown.
                while not disposed.is_set():
                    try:
                        queue.put(callback, timeout=0.05)
                        return
                    except Full:
                        pass

            def on_next(value: _T) -> None:
                enqueue(lambda: observer.on_next(value))

            def on_error(exc: Exception) -> None:
                enqueue(lambda: observer.on_error(exc))

            def on_completed() -> None:
                enqueue(observer.on_completed)

            def dispose() -> None:
                disposed.set()
                # A full queue already wakes the consumer; never block its own
                # callback trying to insert a shutdown sentinel.
                try:
                    queue.put_nowait(lambda: None)
                except Full:
                    pass
                try:
                    subscription.dispose()
                finally:
                    if thread is not current_thread():
                        thread.join()

            thread = Thread(target=run, name=thread_name, daemon=True)
            thread.start()
            try:
                subscription.disposable = source.subscribe(
                    on_next, on_error, on_completed, scheduler=scheduler
                )
            except BaseException:
                dispose()
                raise

            return Disposable(dispose)

        return Observable(subscribe)

    return observe_on
