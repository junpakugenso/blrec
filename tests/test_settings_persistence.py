import asyncio
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from blrec.setting import Settings, SettingsManager


class SettingsPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'settings.toml'
        self.original = 'version = "1.0"\n'
        self.path.write_text(self.original, encoding='utf8')
        self.settings = Settings.load(str(self.path))

    def assert_original(self):
        self.assertEqual(self.path.read_text(encoding='utf8'), self.original)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [self.path])

    def test_write_failure_preserves_old_file(self):
        with patch('blrec.setting.models.os.fsync', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                self.settings.dump()
        self.assert_original()

    def test_replace_failure_preserves_old_file(self):
        with patch('blrec.setting.models.os.replace', side_effect=PermissionError('busy')):
            with self.assertRaises(PermissionError):
                self.settings.dump()
        self.assert_original()

    def test_serialization_failure_preserves_old_file(self):
        with patch.object(Settings, 'dict', side_effect=ValueError('invalid data')):
            with self.assertRaises(ValueError):
                self.settings.dump()
        self.assert_original()

    def test_round_trip(self):
        self.settings.danmaku.record_gift_send = False
        self.settings.dump()
        self.assertFalse(Settings.load(str(self.path)).danmaku.record_gift_send)

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_permissions_preserved(self):
        self.path.chmod(0o640)
        self.settings.dump()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    async def test_cancelled_save_keeps_lock_until_writer_finishes(self):
        manager = SettingsManager(None, self.settings)
        entered, release = threading.Event(), threading.Event()
        snapshots = []
        active = peak = 0
        lock = threading.Lock()

        def save(snapshot):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            snapshots.append(snapshot.danmaku.record_gift_send)
            if len(snapshots) == 1:
                entered.set()
                if not release.wait(3):
                    raise TimeoutError('test writer not released')
            with lock:
                active -= 1

        with patch.object(Settings, 'dump', save):
            first = asyncio.create_task(manager.dump_settings())
            second = None
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                self.settings.danmaku.record_gift_send = False
                first.cancel()
                await asyncio.sleep(0)
                first.cancel()  # Repeated cancellation must not release the lock.
                second = asyncio.create_task(manager.dump_settings())
                await asyncio.sleep(0.05)
                self.assertEqual(snapshots, [True])
            finally:
                release.set()
                results = await asyncio.gather(first, *([second] if second else []),
                                               return_exceptions=True)
            self.assertIsInstance(results[0], asyncio.CancelledError)
            self.assertEqual(snapshots, [True, False])
            self.assertEqual(peak, 1)

    async def test_write_exception_releases_lock_for_retry(self):
        manager = SettingsManager(None, self.settings)
        with patch.object(Settings, 'dump', side_effect=[OSError('failed'), None]) as save:
            with self.assertRaises(OSError):
                await manager.dump_settings()
            await asyncio.wait_for(manager.dump_settings(), 1)
            self.assertEqual(save.call_count, 2)
