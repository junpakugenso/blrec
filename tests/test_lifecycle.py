import asyncio
import unittest

from blrec.utils.mixins import AsyncStoppableMixin, StoppableMixin, SwitchableMixin


class Toggle(SwitchableMixin):
    failure = None
    def _do_enable(self):
        if self.failure: raise self.failure
    def _do_disable(self):
        if self.failure: raise self.failure


class SyncTask(StoppableMixin):
    failure = None
    def _do_start(self):
        if self.failure: raise self.failure
    def _do_stop(self):
        if self.failure: raise self.failure


class AsyncTask(AsyncStoppableMixin):
    failure = None
    async def _do_start(self):
        if self.failure: raise self.failure
    async def _do_stop(self):
        if self.failure: raise self.failure


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def test_sync_failure_retry_and_idempotence(self):
        for cls, start, stop, attr, initial in (
            (SyncTask, 'start', 'stop', 'stopped', True),
            (Toggle, 'enable', 'disable', 'enabled', False),
        ):
            with self.subTest(cls=cls):
                task = cls()
                task.failure = RuntimeError('start failed')
                with self.assertRaises(RuntimeError): getattr(task, start)()
                self.assertEqual(getattr(task, attr), initial)
                task.failure = None
                getattr(task, start)()
                task.failure = RuntimeError('stop failed')
                getattr(task, start)()  # Already started: do nothing.
                with self.assertRaises(RuntimeError): getattr(task, stop)()
                self.assertEqual(getattr(task, attr), not initial)
                task.failure = None
                getattr(task, stop)()
                self.assertEqual(getattr(task, attr), initial)

    async def test_async_failure_and_cancellation_are_retryable(self):
        for error in (RuntimeError('failure'), asyncio.CancelledError()):
            with self.subTest(error=type(error)):
                task = AsyncTask()
                task.failure = error
                with self.assertRaises(type(error)): await task.start()
                self.assertTrue(task.stopped)
                task.failure = None
                await task.start()
                task.failure = error
                with self.assertRaises(type(error)): await task.stop()
                self.assertFalse(task.stopped)
                task.failure = None
                await task.stop()
                self.assertTrue(task.stopped)
