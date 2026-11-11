import hashlib
import random

import pytest

from rolling_dedup.chunker import Config, MASK64, MAX_BYTES, TABLE, WINDOW, chunks, rolling_hashes, spans


def direct_hash(window):
    # Recompute every contribution without the production recurrence or rotate.
    value = 0
    for j, byte in enumerate(window):
        shift = len(window)-1-j
        item = int.from_bytes(hashlib.sha256(b'rolling-chunk-dedup-v1:'+bytes([byte])).digest()[:8], 'big')
        moved = item if shift == 0 else (item*2**shift + item//2**(64-shift)) % 2**64
        value ^= moved
    return value


@pytest.mark.parametrize('seed', range(5))
def test_rolling_recurrence_against_independent_full_windows(seed):
    data = random.Random(seed).randbytes(200)
    assert list(rolling_hashes(data)) == [direct_hash(data[max(0, i+1-WINDOW):i+1]) for i in range(len(data))]


def test_window_locality_after_insertion():
    base = random.Random(7).randbytes(500)
    position, insertion = 150, b'new-prefix'
    edited = base[:position]+insertion+base[position:]
    before, after = list(rolling_hashes(base)), list(rolling_hashes(edited))
    for i in range(position+WINDOW-1, len(base)):
        assert before[i] == after[i+len(insertion)]


def test_boundaries_against_naive_window_scan():
    data = random.Random(3).randbytes(3000)
    config = Config(minimum=64, maximum=400, mask_bits=7)
    expected, start = [], 0
    for i in range(1, len(data)+1):
        fingerprint = direct_hash(data[max(0, i-WINDOW):i])
        if i-start >= 400 or (i-start >= 64 and fingerprint % 128 == 0):
            expected.append((start, i))
            start = i
    if start < len(data):
        expected.append((start, len(data)))
    assert spans(data, config) == expected


@pytest.mark.parametrize('length', [0, 1, 31, 255, 256, 4096, 20000])
def test_reconstruction_and_size_limits(length):
    data = random.Random(length).randbytes(length)
    blocks = chunks(data)
    assert b''.join(blocks) == data
    assert all(256 <= len(b) <= 4096 for b in blocks[:-1])
    assert not blocks or 1 <= len(blocks[-1]) <= 4096
    assert spans(data) == spans(data)


def test_fixed_size_and_no_empty_terminal_chunk():
    assert list(map(len, chunks(bytes(256), Config(method='fixed', fixed_size=64)))) == [64]*4
    assert list(map(len, chunks(bytes(257), Config(method='fixed', fixed_size=64)))) == [64]*4+[1]


@pytest.mark.parametrize('settings', [{'method': 'unknown'}, {'minimum': 31}, {'maximum': 65537}, {'mask_bits': True}, {'mask_bits': 4}, {'minimum': 500, 'maximum': 400}, {'fixed_size': 0}])
def test_invalid_config(settings):
    with pytest.raises(ValueError):
        Config(**settings)


def test_input_limits():
    for data in ('abc', bytearray(b'abc'), bytes(MAX_BYTES+1)):
        with pytest.raises(ValueError):
            chunks(data)


def test_table_and_state_are_64_bit():
    assert len(TABLE) == len(set(TABLE)) == 256
    assert all(0 <= h <= MASK64 for h in rolling_hashes(bytes(range(256))*2))
