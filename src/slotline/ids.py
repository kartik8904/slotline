import os
import time
import uuid


def new_uuid7() -> uuid.UUID:
    """UUID v7 (RFC 9562): a 48-bit millisecond timestamp first, so ids sort by creation time.

    Python 3.13 has no uuid.uuid7(). Within one millisecond the order is random, which is fine:
    ids stay unique and totally ordered, which is all cursor pagination needs.
    """
    millis = time.time_ns() // 1_000_000
    entropy = int.from_bytes(os.urandom(10))  # 80 random bits
    value = (millis & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version
    value |= ((entropy >> 68) & 0xFFF) << 64  # rand_a: 12 bits
    value |= 0b10 << 62  # variant
    value |= entropy & ((1 << 62) - 1)  # rand_b: 62 bits
    return uuid.UUID(int=value)
