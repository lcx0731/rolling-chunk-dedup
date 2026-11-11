import json
import random
import struct

import pytest

from rolling_dedup import Config, inspect_archive, pack, unpack
from rolling_dedup import archive as module


def rewrite(encoded, change):
    length = struct.unpack('>I', encoded[8:12])[0]
    meta = json.loads(encoded[12:12+length])
    payload = encoded[12+length:]
    change(meta)
    raw = json.dumps(meta, separators=(',', ':')).encode()
    return encoded[:8]+struct.pack('>I',len(raw))+raw+payload


@pytest.mark.parametrize('method', ['fixed', 'buzhash'])
def test_archive_roundtrip_and_accounting(method):
    base = random.Random(10).randbytes(12000)
    versions = [b'', base, base[:3000]+b'inserted'+base[3000:], base]
    config = Config(method=method)
    encoded = pack(versions, config)
    assert unpack(encoded) == versions
    assert pack(versions, config) == encoded
    stats = inspect_archive(encoded)
    assert stats['raw_bytes'] == sum(map(len, versions))
    assert stats['archive_bytes'] == len(encoded)
    assert stats['metadata_and_header_bytes']+stats['unique_payload_bytes'] == len(encoded)
    assert stats['payload_bytes_saved'] >= len(base)


def test_empty_archive_entries():
    out = pack([b'', b''])
    assert unpack(out) == [b'', b'']
    assert inspect_archive(out)['unique_chunks'] == 0


def test_repeated_chunk_payload_is_stored_once():
    config = Config(method='fixed', fixed_size=32)
    block = bytes(range(32))
    encoded = pack([block*10], config)
    stats = inspect_archive(encoded)
    assert stats['unique_chunks'] == 1
    assert stats['chunk_references'] == 10
    assert stats['unique_payload_bytes'] == 32
    assert unpack(encoded) == [block*10]


def test_hash_collision_is_not_silent_deduplication(monkeypatch):
    monkeypatch.setattr(module, 'digest', lambda _: '0'*64)
    with pytest.raises(ValueError, match='collision'):
        pack([b'a'*32+b'b'*32], Config(method='fixed', fixed_size=32))


def test_payload_corruption_rejected():
    encoded = pack([b'a'*64])
    corrupted = encoded[:-1]+bytes([encoded[-1]^1])
    with pytest.raises(ValueError, match='chunk digest mismatch'):
        unpack(corrupted)


@pytest.mark.parametrize('cut', [0, 3, 8, 11, 20, -1])
def test_truncated_archives_rejected(cut):
    encoded = pack([b'a'*64])
    with pytest.raises(ValueError):
        unpack(encoded[:cut])


def test_trailing_bytes_rejected():
    with pytest.raises(ValueError, match='trailing'):
        unpack(pack([b'abc'])+b'x')


@pytest.mark.parametrize('field,value', [('version', True), ('version', 2), ('entries', []), ('chunks', 'bad')])
def test_invalid_top_level_values(field, value):
    encoded = rewrite(pack([b'x'*64]), lambda m: m.__setitem__(field, value))
    with pytest.raises(ValueError):
        unpack(encoded)


def test_unknown_keys_and_duplicate_json_keys():
    with pytest.raises(ValueError, match='fields'):
        unpack(rewrite(pack([b'a']), lambda m: m.__setitem__('extra', 0)))
    raw = b'{"version":1,"version":1}'
    with pytest.raises(ValueError, match='manifest JSON'):
        unpack(module.MAGIC+struct.pack('>I',len(raw))+raw)


@pytest.mark.parametrize('index', [-1, 1, True, '0'])
def test_bad_references(index):
    encoded = rewrite(pack([b'a'*64]), lambda m: m['entries'][0].__setitem__('refs', [index]))
    with pytest.raises(ValueError, match='chunk index'):
        unpack(encoded)


def test_entry_size_and_hash_checked():
    encoded = pack([b'a'*64])
    with pytest.raises(ValueError, match='entry size'):
        unpack(rewrite(encoded, lambda m: m['entries'][0].__setitem__('size', 63)))
    with pytest.raises(ValueError, match='entry digest'):
        unpack(rewrite(encoded, lambda m: m['entries'][0].__setitem__('sha256', '0'*64)))


def test_reordered_references_detected_by_entry_hash():
    encoded = pack([b'a'*32+b'b'*32], Config(method='fixed', fixed_size=32))
    with pytest.raises(ValueError, match='entry digest'):
        unpack(rewrite(encoded, lambda m: m['entries'][0].__setitem__('refs',[1,0])))


def test_declared_boundaries_recomputed():
    encoded = pack([b'a'*32+b'b'*32], Config(method='fixed', fixed_size=32))
    with pytest.raises(ValueError, match='declared chunk boundaries'):
        unpack(rewrite(encoded, lambda m: m['config'].__setitem__('fixed_size',64)))


def test_unused_stored_chunks_rejected():
    encoded = pack([b'a'*32, b'b'*32], Config(method='fixed', fixed_size=32))
    with pytest.raises(ValueError, match='unreferenced'):
        unpack(rewrite(encoded, lambda m: m['entries'].pop()))


def test_output_expansion_is_bounded_before_join():
    encoded = pack([b'a'*65536], Config(method='fixed', fixed_size=65536))
    with pytest.raises(ValueError, match='entry size'):
        unpack(rewrite(encoded, lambda m: m['entries'][0].__setitem__('refs', [0]*65536)))


@pytest.mark.parametrize('versions', [[], [b'a']*33, ['a'], b'abc'])
def test_invalid_pack_input(versions):
    with pytest.raises(ValueError):
        pack(versions)
