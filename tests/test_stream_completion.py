import asyncio
import threading
import unittest
import uuid
from unittest.mock import Mock

import blrec.setting  # Preserve the application's import order.
from reactivex.subject import Subject
from blrec.core.stream_recorder_impl import StreamRecorderImpl
from blrec.event.event_emitter import EventEmitter
from blrec.utils.operators.observe_on import observe_on_new_thread


class TestStreamRecorder(StreamRecorderImpl):
    def __init__(self):
        EventEmitter.__init__(self)
        self._logger = Mock()
        self._live = Mock(room_id=1)
        self._stream_param_holder = Mock()
        self._dl_statistics = Mock()
        self._rec_statistics = Mock()
        self._threads = []
        self._files = []
        self._completed = False
        self.source = Subject()
        self.worker_name = 'completion-test-' + uuid.uuid4().hex
        self.created_threads = []

    def _run(self):
        self._subscription = self.source.pipe(observe_on_new_thread(
            queue_size=1, thread_name=self.worker_name)).subscribe(
                on_completed=self._on_completed)

    def _thread_factory(self, name):
        factory = super()._thread_factory(name)
        def create(target):
            thread = factory(target)
            original_join = thread.join
            # Fail quickly on the original 30-second wait cycle.
            thread.join = lambda timeout=None: original_join(
                min(timeout, 0.2) if timeout is not None else None)
            self.created_threads.append(thread)
            return thread
        return create


class StreamCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_natural_completion_listener_can_stop_without_wait_cycle(self):
        recorder = TestStreamRecorder()
        done = asyncio.Event()
        alive_at_stop = []
        calls = []
        class Listener:
            async def on_stream_recording_completed(self):
                calls.append('completed')
                await recorder.stop()
                alive_at_stop.extend(t.name for t in recorder.created_threads if t.is_alive())
                done.set()
        recorder.add_listener(Listener())
        await recorder.start()
        recorder.source.on_completed()
        await asyncio.wait_for(done.wait(), 2)
        # Let the callback return, then verify all real worker threads exit.
        for thread in threading.enumerate():
            if thread.name == recorder.worker_name or thread in recorder.created_threads:
                await asyncio.to_thread(thread.join, 1)
                self.assertFalse(thread.is_alive(), thread.name)
        self.assertEqual(alive_at_stop, [])
        self.assertEqual(calls, ['completed'])

    async def test_manual_stop_waits_for_completion_listener(self):
        recorder = TestStreamRecorder()
        calls = []
        class Listener:
            async def on_stream_recording_completed(self):
                await asyncio.sleep(0.01)
                calls.append('completed')
        recorder.add_listener(Listener())
        await recorder.start()
        await recorder.stop()
        self.assertEqual(calls, ['completed'])
        self.assertTrue(all(not t.is_alive() for t in recorder.created_threads))
