import asyncio
import base64
import copy
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from lxml import etree

import blrec.setting  # Match application startup order (existing import cycle).
from blrec.bili.gift_protocol import decode_gifts
from blrec.core.danmaku_receiver import DanmakuReceiver
from blrec.core.danmaku_dumper import DanmakuDumper
from blrec.core.models import GiftSendMsg
from blrec.danmaku.io import DanmakuWriter


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number, value):
    if isinstance(value, int):
        return varint(number << 3) + varint(value)
    if isinstance(value, str):
        value = value.encode('utf8')
    return varint((number << 3) | 2) + varint(len(value)) + value


def payload(count=1, coin='gold', price=100):
    # Independent wire fixture, not generated from the production descriptor.
    gift = (field(2, 'flower<&') + field(3, 2) + field(5, price)
            + field(8, coin) + field(10, 1700000010) + field(99, 'future'))
    raw = field(1, 123) + field(2, 'viewer<&') + field(10, gift) * count
    return base64.b64encode(raw).decode()


def v2(**kwargs):
    return {'cmd': 'SEND_GIFT_V2', 'data': {'pb': payload(**kwargs)}}


def dumper_for(receiver):
    dumper = object.__new__(DanmakuDumper)
    dumper._receiver = receiver
    dumper._stream_recording_interrupted = False
    dumper._record_start_time = 1700000000
    dumper._delta = 0
    dumper.record_gift_send = True
    dumper.record_free_gifts = True
    return dumper


class GiftProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.receiver = DanmakuReceiver(SimpleNamespace(room_id=1), object())

    async def test_batch_and_legacy_and_raw_unchanged(self):
        message = v2(count=2)
        original = copy.deepcopy(message)
        await self.receiver.on_danmaku_received(message)
        gifts = [await self.receiver.get_message() for _ in range(2)]
        self.assertEqual(message, original)
        self.assertEqual(gifts[0], gifts[1])
        self.assertIsInstance(gifts[0], GiftSendMsg)
        self.assertEqual(gifts[0].uid, 123)
        self.assertEqual(gifts[0].count, 2)
        self.assertEqual(gifts[0].timestamp, 1700000010)
        await self.receiver.on_danmaku_received(
            {'cmd': 'SEND_GIFT', 'data': decode_gifts(payload())[0]})
        self.assertEqual(await self.receiver.get_message(), gifts[0])

    async def test_invalid_payload_does_not_stop_following_gifts(self):
        for bad in ('!', 'AAAA', '', None, base64.b64encode(b'\x52\xff').decode()):
            await self.receiver.on_danmaku_received(
                {'cmd': 'SEND_GIFT_V2', 'data': {'pb': bad}})
        await self.receiver.on_danmaku_received({'cmd': 'SEND_GIFT_V2', 'data': {}})
        self.assertTrue(self.receiver._queue.empty())
        await self.receiver.on_danmaku_received(v2())
        self.assertEqual(self.receiver._queue.qsize(), 1)

    async def test_combo_notifications_not_counted(self):
        for cmd in ('COMBO_SEND', 'GIFT_COMBO'):
            await self.receiver.on_danmaku_received({'cmd': cmd, 'data': {}})
        self.assertTrue(self.receiver._queue.empty())

    async def test_full_queue_keeps_latest(self):
        self.receiver._queue = asyncio.Queue(maxsize=1)
        await self.receiver.on_danmaku_received(v2(count=2))
        self.assertEqual(self.receiver._queue.qsize(), 1)

    async def test_xml_fields_and_filter_settings(self):
        dumper = dumper_for(self.receiver)
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.xml')
            async with DanmakuWriter(path) as writer:
                for enabled, free, coin in (
                    (True, True, 'gold'), (True, False, 'silver'),
                    (False, True, 'gold'), (True, True, 'silver'),
                ):
                    dumper.record_gift_send = enabled
                    dumper.record_free_gifts = free
                    await self.receiver.on_danmaku_received(v2(coin=coin))
                    task = asyncio.create_task(dumper._dumping_loop(writer))
                    # Queue join is unavailable here; wait for the consumer to
                    # request its next message after completing the write.
                    for _ in range(1000):
                        if self.receiver._queue._getters:
                            break
                        await asyncio.sleep(0.001)
                    else:
                        self.fail('gift consumer did not finish')
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            gifts = etree.parse(path).findall('gift')
            self.assertEqual(len(gifts), 2)
            self.assertEqual(gifts[0].get('ts'), '10.000')
            self.assertEqual(gifts[0].get('giftname'), 'flower<&')
            self.assertEqual(gifts[0].get('user'), 'viewer<&')
            self.assertEqual(gifts[0].get('giftcount'), '2')
            self.assertEqual(gifts[0].get('price'), '100')

    def test_invalid_fields_and_zero_price(self):
        self.assertEqual(decode_gifts(payload(coin='silver', price=0))[0]['price'], 0)
        for bad in (payload(count=0), payload(coin='invalid')):
            with self.assertRaises(ValueError):
                decode_gifts(bad)

    @unittest.skipUnless(os.environ.get('BLREC_GIFT_SAMPLE_ZIP'), 'external recording not set')
    async def test_real_recording_archive(self):
        dumper = dumper_for(self.receiver)
        messages = records = 0
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'replay.xml')
            async with DanmakuWriter(path) as writer:
                with zipfile.ZipFile(os.environ['BLREC_GIFT_SAMPLE_ZIP']) as archive:
                    name = next(n for n in archive.namelist() if n.endswith('.jsonl'))
                    with archive.open(name) as stream:
                        for line in stream:
                            message = json.loads(line)
                            if message.get('cmd') != 'SEND_GIFT_V2':
                                continue
                            decoded = decode_gifts(message['data']['pb'])
                            messages += 1
                            await self.receiver.on_danmaku_received(message)
                            self.assertEqual(self.receiver._queue.qsize(), len(decoded))
                            for expected in decoded:
                                gift = await self.receiver.get_message()
                                self.assertEqual(gift.gift_name, expected['giftName'])
                                await writer.write_gift_send_record(dumper._make_gift_send_record(gift))
                                records += 1
            self.assertGreater(messages, 0)
            self.assertEqual(len(etree.parse(path).findall('gift')), records)
            print(f'Real recording: {messages} SEND_GIFT_V2 messages -> {records} XML gifts')
