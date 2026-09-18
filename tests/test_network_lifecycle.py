import asyncio
import os
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

import blrec.setting  # Preserve the application's existing import order.
from aiohttp import web
from aiohttp.test_utils import TestServer
from blrec.application import Application
from blrec.bili import helpers, net
from blrec.bili.api import WebApi
from blrec.bili.live import Live
from blrec.core.cover_downloader import CoverDownloader


class NetworkImportTests(unittest.TestCase):
    def test_import_does_not_create_a_connector(self):
        code = ('from unittest.mock import patch\n'
                'with patch("aiohttp.TCPConnector") as create:\n'
                ' import blrec.bili.net\n'
                ' create.assert_not_called()\n')
        result = subprocess.run([sys.executable, '-c', code], text=True,
                                capture_output=True, env={**os.environ,
                                'PYTHONPATH': os.pathsep.join(sys.path)})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_separate_loops_get_separate_pools(self):
        loops = [asyncio.new_event_loop(), asyncio.new_event_loop()]
        async def acquire():
            return net.get_connector()
        try:
            pools = [loop.run_until_complete(acquire()) for loop in loops]
            self.assertIsNot(pools[0], pools[1])
            self.assertTrue(all(pool._loop is loop for pool, loop in zip(pools, loops)))
            loops[0].run_until_complete(net.close_connector())
            self.assertTrue(pools[0].closed)
            self.assertFalse(pools[1].closed)
        finally:
            for loop in loops:
                loop.run_until_complete(net.close_connector())
                loop.close()


class NetworkLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.proxy_patch = patch.dict(os.environ, {'NO_PROXY': '127.0.0.1,localhost'})
        self.proxy_patch.start()
        self.addCleanup(self.proxy_patch.stop)
        self.transports = set()
        self.block_nav = False
        self.request_entered, self.release_request = asyncio.Event(), asyncio.Event()
        async def respond(request):
            self.transports.add(request.transport)
            if self.block_nav and request.path.endswith('/nav'):
                self.request_entered.set()
                await self.release_request.wait()
            return web.json_response({'code': 0, 'data': {'room_id': 123}})
        app = web.Application()
        app.router.add_get('/{path:.*}', respond)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.addAsyncCleanup(net.close_connector)
        self.url = str(self.server.make_url('/'))

    async def test_live_sessions_share_and_reuse_current_loop_pool(self):
        first, second = Live(1), Live(2)
        self.addAsyncCleanup(first.deinit)
        self.addAsyncCleanup(second.deinit)
        pool = first.session.connector
        self.assertIs(pool, second.session.connector)
        self.assertIs(pool._loop, asyncio.get_running_loop())
        self.assertEqual(pool.limit, 200)
        self.assertEqual(first.session.timeout.total, 10)
        self.assertTrue(first.session.trust_env)
        async with first.session.get(self.url) as response:
            self.assertEqual(response.status, 200)
            await response.read()
        await first.deinit()
        self.assertFalse(pool.closed)
        async with second.session.get(self.url) as response:
            await response.read()
        self.assertEqual(len(self.transports), 1)
        await second.deinit()
        await net.close_connector()
        self.assertTrue(pool.closed)
        await net.close_connector()  # Shutdown is idempotent.
        self.assertIsNot(net.get_connector(), pool)

    async def test_helpers_and_cover_use_real_local_http_and_release_pool(self):
        def local_api(*args, **kwargs):
            api = WebApi(*args, **kwargs)
            api.base_api_urls = api.base_live_api_urls = [self.url.rstrip('/')]
            return api
        with patch.object(helpers, 'WebApi', side_effect=local_api):
            self.assertEqual(await helpers.room_init(123), {'room_id': 123})
            self.assertEqual((await helpers.get_nav('test=fixture'))['code'], 0)
        cover = object.__new__(CoverDownloader)
        self.assertIn(b'room_id', await cover._fetch_cover(self.url))
        self.assertEqual(len(self.transports), 1)
        pool = net.get_connector()
        await net.close_connector()
        self.assertTrue(pool.closed)
        self.assertFalse(pool._conns)

    async def test_cancelled_request_releases_slot_and_pool_remains_usable(self):
        def local_api(*args, **kwargs):
            api = WebApi(*args, **kwargs)
            api.base_api_urls = [self.url.rstrip('/')]
            return api
        self.block_nav = True
        with patch.object(helpers, 'WebApi', side_effect=local_api):
            request = asyncio.create_task(helpers.get_nav('test=fixture'))
            try:
                await asyncio.wait_for(self.request_entered.wait(), 2)
                pool = net.get_connector()
                request.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await request
                self.assertFalse(pool.closed)
                self.assertFalse(pool._acquired)
                self.block_nav = False
                self.assertEqual((await helpers.get_nav('test=fixture'))['code'], 0)
            finally:
                self.release_request.set()
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)

    def make_application(self):
        app = object.__new__(Application)
        app._task_manager = Mock(stop_all_tasks=AsyncMock(), destroy_all_tasks=AsyncMock())
        app._destroy = Mock()
        return app

    async def test_application_exit_closes_pool_after_task_destruction(self):
        app = self.make_application()
        pool = net.get_connector()
        async def destroyed():
            self.assertFalse(pool.closed)
        app._task_manager.destroy_all_tasks.side_effect = destroyed
        app._destroy.side_effect = lambda: self.assertTrue(pool.closed)
        restarted_pools = []
        async def relaunched():
            self.assertTrue(pool.closed)
            restarted_pools.append(net.get_connector())
        app.launch = AsyncMock(side_effect=relaunched)
        await app.restart()
        app._task_manager.stop_all_tasks.assert_awaited_once_with(force=False)
        self.assertTrue(pool.closed)
        # The next application lifecycle acquires a fresh pool on the same loop.
        new_pool = restarted_pools[0]
        self.assertIsNot(pool, new_pool)
        pool = new_pool
        await app._exit()
        self.assertTrue(new_pool.closed)

    async def test_failed_shutdown_keeps_live_tasks_pool_until_retry(self):
        for step in ('stop_all_tasks', 'destroy_all_tasks'):
            with self.subTest(step=step):
                app = self.make_application()
                pool = net.get_connector()
                getattr(app._task_manager, step).side_effect = RuntimeError('failed')
                with self.assertRaises(RuntimeError):
                    await app._exit()
                self.assertFalse(pool.closed)
                self.assertIs(net.get_connector(), pool)
                app._destroy.assert_not_called()
                getattr(app._task_manager, step).side_effect = None
                await app._exit()
                self.assertTrue(pool.closed)
