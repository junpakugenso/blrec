"""Minimal SEND_GIFT_V2 schema; unknown protobuf fields are ignored.

Field numbers: https://github.com/xfgryujk/blivedm/blob/master/blivedm/models/pb.py
Only fields consumed by blrec's XML gift record are declared here.
"""

import base64
from typing import Any, Dict, List

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import DecodeError


def _message_class() -> Any:
    schema = descriptor_pb2.FileDescriptorProto(
        name='blrec_send_gift_v2.proto', package='blrec.gift', syntax='proto3'
    )
    field = descriptor_pb2.FieldDescriptorProto
    for name, fields in (
        ('Gift', (
            ('gift_name', 2, field.TYPE_STRING),
            ('num', 3, field.TYPE_INT64),
            ('price', 5, field.TYPE_INT64),
            ('coin_type', 8, field.TYPE_STRING),
            ('timestamp', 10, field.TYPE_INT64),
        )),
        ('Broadcast', (
            ('uid', 1, field.TYPE_INT64),
            ('uname', 2, field.TYPE_STRING),
        )),
    ):
        message = schema.message_type.add(name=name)
        for field_name, number, kind in fields:
            message.field.add(
                name=field_name, number=number, type=kind,
                label=field.LABEL_OPTIONAL,
            )
    schema.message_type[1].field.add(
        name='gifts', number=10, type=field.TYPE_MESSAGE,
        type_name='.blrec.gift.Gift', label=field.LABEL_REPEATED,
    )
    pool = descriptor_pool.DescriptorPool()
    pool.Add(schema)
    return message_factory.GetMessageClass(
        pool.FindMessageTypeByName('blrec.gift.Broadcast')
    )


_Broadcast = _message_class()


def decode_gifts(payload: str) -> List[Dict[str, Any]]:
    """Return legacy-shaped gift data without modifying the raw message."""
    if not isinstance(payload, str) or not payload or len(payload) > 4 * 1024**2:
        raise ValueError('Invalid SEND_GIFT_V2 payload size or type')
    try:
        message = _Broadcast.FromString(base64.b64decode(payload, validate=True))
    except (ValueError, DecodeError) as exc:
        raise ValueError('Invalid SEND_GIFT_V2 encoding') from exc
    if not message.gifts:
        raise ValueError('SEND_GIFT_V2 has no gift items')
    records = []
    for gift in message.gifts:
        if (not gift.gift_name or gift.num <= 0 or gift.timestamp <= 0
                or gift.price < 0 or gift.coin_type not in ('gold', 'silver', 'sliver')):
            raise ValueError('Invalid SEND_GIFT_V2 gift fields')
        records.append(dict(
            giftName=gift.gift_name, num=gift.num, price=gift.price,
            coin_type=gift.coin_type, timestamp=gift.timestamp,
            uid=message.uid, uname=message.uname,
        ))
    return records
