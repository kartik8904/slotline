import uuid

from slotline.domain.principal import ALL_SCOPES, Principal, Role, Scope
from slotline.domain.slugs import slugify
from slotline.pagination import decode_cursor, encode_cursor, paginate


def test_all_scopes_covers_every_scope() -> None:
    assert ALL_SCOPES == {scope.value for scope in Scope}


def test_user_principal_flags() -> None:
    principal = Principal(
        org_id=uuid.uuid4(), role=Role.STAFF, scopes=ALL_SCOPES, user_id=uuid.uuid4()
    )
    assert principal.is_user
    assert principal.has_scope(Scope.BOOKINGS_WRITE)


def test_key_principal_has_only_its_scopes() -> None:
    principal = Principal(
        org_id=uuid.uuid4(),
        role=None,
        scopes=frozenset({Scope.BOOKINGS_READ.value}),
        key_id=uuid.uuid4(),
    )
    assert not principal.is_user
    assert principal.has_scope(Scope.BOOKINGS_READ)
    assert not principal.has_scope(Scope.BOOKINGS_WRITE)


def test_slugify() -> None:
    assert slugify("Dr Mehta's Clinic!") == "dr-mehta-s-clinic"
    assert slugify("  --Salon  &  Spa--  ") == "salon-spa"
    assert slugify("日本語") == "org"
    assert len(slugify("a" * 200)) == 40
    assert not slugify("a" * 39 + "-b").endswith("-")


def test_cursor_round_trip_and_end_of_list() -> None:
    value = uuid.uuid4()
    assert decode_cursor(encode_cursor(value)) == value
    assert decode_cursor(None) is None


class Row:
    def __init__(self) -> None:
        self.id = uuid.uuid4()


def test_paginate_trims_the_extra_row_and_sets_next_cursor() -> None:
    rows = [Row() for _ in range(4)]
    items, cursor = paginate(rows, 3)
    assert items == rows[:3]
    assert cursor == encode_cursor(rows[2].id)
    assert paginate(rows[:3], 3) == (rows[:3], None)
    assert paginate([], 3) == ([], None)
