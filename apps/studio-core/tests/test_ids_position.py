from hypothesis import given
from hypothesis import strategies as st

from pbs_core.domain.ids import UlidFactory, is_ulid
from pbs_core.domain.position import key_between


def test_ulids_are_valid_and_monotonic_within_one_ms() -> None:
    factory = UlidFactory(clock_ms=lambda: 1_700_000_000_000)
    ids = [factory.new() for _ in range(1000)]
    assert all(is_ulid(i) for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_append_keys_sort_in_order() -> None:
    keys: list[str] = []
    last = None
    for _ in range(500):
        last = key_between(last, None)
        keys.append(last)
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


@given(st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=60))
def test_random_inserts_keep_order(choices: list[int]) -> None:
    keys = [key_between(None, None)]
    for c in choices:
        i = c % (len(keys) + 1)
        before = keys[i - 1] if i > 0 else None
        after = keys[i] if i < len(keys) else None
        k = key_between(before, after)
        assert (before is None or before < k) and (after is None or k < after)
        keys.insert(i, k)
    assert keys == sorted(keys)
