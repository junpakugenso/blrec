import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

import blrec.setting  # Existing application import order.
from blrec.core.recorder import Recorder
from blrec.utils.mixins import AsyncStoppableMixin


class Resource:
    def __init__(self):
        self.listeners = []
        self.enabled = False
        self.stopped = True
    def add_listener(self, item):
        if item not in self.listeners: self.listeners.append(item)
    def remove_listener(self, item):
        if item in self.listeners: self.listeners.remove(item)
    def enable(self): self.enabled = True
    def disable(self): self.enabled = False
    def start(self): self.stopped = False
    def stop(self): self.stopped = True


class RecorderLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_recorder(self):
        recorder = object.__new__(Recorder)
        AsyncStoppableMixin.__init__(recorder)
        recorder._recording = False
        recorder._stream_available = True
        recorder.save_raw_danmaku = True
        recorder._logger = Mock()
        recorder._live = Mock()
        recorder._live.is_living.return_value = True
        recorder._print_live_info = Mock()
        recorder._prepare = AsyncMock()
        recorder._emit = AsyncMock()
        for name in ('live_monitor', 'danmaku_dumper', 'raw_danmaku_dumper',
                     'cover_downloader', 'danmaku_receiver', 'raw_danmaku_receiver'):
            setattr(recorder, '_' + name, Resource())
        recorder._stream_recorder = Resource()
        recorder._stream_recorder.start = AsyncMock()
        recorder._stream_recorder.stop = AsyncMock()
        return recorder

    def assert_clean(self, recorder):
        self.assertFalse(recorder.recording)
        for name in ('live_monitor', 'danmaku_dumper', 'raw_danmaku_dumper',
                     'cover_downloader', 'danmaku_receiver', 'raw_danmaku_receiver',
                     'stream_recorder'):
            resource = getattr(recorder, '_' + name)
            self.assertEqual(resource.listeners, [], name)
            self.assertFalse(resource.enabled, name)
            self.assertTrue(resource.stopped, name)

    async def test_prepare_failure_cleans_resources_and_allows_restart(self):
        for failure in (RuntimeError('prepare failed'), asyncio.CancelledError()):
            recorder = self.make_recorder()
            recorder._prepare.side_effect = failure
            with self.assertRaises(type(failure)): await recorder.start()
            self.assertTrue(recorder.stopped)
            self.assert_clean(recorder)
            recorder._prepare.side_effect = None
            await recorder.start()
            await recorder.stop()
            self.assert_clean(recorder)

    async def test_stream_start_failure_cleans_helpers(self):
        recorder = self.make_recorder()
        recorder._stream_recorder.start.side_effect = RuntimeError('stream failed')
        with self.assertRaises(RuntimeError): await recorder.start()
        self.assert_clean(recorder)

    async def test_cancel_after_stream_started_stops_stream_without_reentry(self):
        recorder = self.make_recorder()
        recorder._emit.side_effect = asyncio.CancelledError()
        async def stop():
            await recorder.on_stream_recording_completed()
        recorder._stream_recorder.stop.side_effect = stop
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(recorder.start(), 1)
        recorder._stream_recorder.stop.assert_awaited_once()
        self.assert_clean(recorder)

    async def test_stop_failure_can_be_retried(self):
        recorder = self.make_recorder()
        await recorder.start()
        recorder._stream_recorder.stop.side_effect = RuntimeError('stop failed')
        with self.assertRaises(RuntimeError): await recorder.stop()
        self.assertFalse(recorder.stopped)
        self.assertTrue(recorder.recording)
        recorder._stream_recorder.stop.side_effect = None
        await recorder.stop()
        self.assert_clean(recorder)
