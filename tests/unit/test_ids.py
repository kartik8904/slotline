import time
import uuid

from slotline.ids import new_uuid7


def test_version_and_variant_bits() -> None:
    value = new_uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_embeds_the_current_millisecond_timestamp() -> None:
    before = int(time.time() * 1000)
    value = new_uuid7()
    after = int(time.time() * 1000)
    assert before <= value.int >> 80 <= after


def test_ids_sort_by_creation_time_and_are_unique() -> None:
    first = new_uuid7()
    time.sleep(0.005)
    second = new_uuid7()
    assert first < second
    ids = [new_uuid7() for _ in range(2000)]
    assert len(set(ids)) == len(ids)
    timestamps = [i.int >> 80 for i in ids]
    assert timestamps == sorted(timestamps)
