"""Versioned, bounded, in-memory archives storing unique chunks in first-use order.

SHA-256 checks detect inconsistent bytes, not an attacker who can rewrite the
manifest and its hashes. No filenames, paths, compression, or encryption exist.
"""

from dataclasses import asdict
import hashlib
import json
import re
import struct

from .chunker import Config, MAX_BYTES, chunks


MAGIC = b'RCDUP1\r\n'
MAX_ARCHIVE = 16*1024*1024
MAX_MANIFEST = 4*1024*1024
MAX_REFERENCES = 65536


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer from {low} to {high}')
    return value


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('unknown or missing manifest fields')


def _hash(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('invalid SHA-256 digest')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate manifest key')
        result[key] = value
    return result


def pack(versions, config=Config()):
    if not isinstance(versions, (list, tuple)) or not 1 <= len(versions) <= 32 or not all(isinstance(v, bytes) for v in versions):
        raise ValueError('provide 1 to 32 byte strings')
    if sum(map(len, versions)) > MAX_BYTES:
        raise ValueError('combined input exceeds 8 MiB')
    if not isinstance(config, Config):
        raise ValueError('config must be a Config object')
    unique, lookup, entries = [], {}, []
    total_refs = 0
    for version in versions:
        refs = []
        for block in chunks(version, config):
            key = digest(block)
            if key in lookup:
                index = lookup[key]
                if unique[index] != block:
                    raise ValueError('chunk digest collision: unequal bytes cannot be merged')
            else:
                index = len(unique)
                lookup[key] = index
                unique.append(block)
            refs.append(index)
        total_refs += len(refs)
        if total_refs > MAX_REFERENCES:
            raise ValueError('too many chunk references')
        entries.append({'size': len(version), 'sha256': digest(version), 'refs': refs})
    manifest = {'version': 1, 'config': asdict(config), 'chunks': [{'size': len(b), 'sha256': digest(b)} for b in unique], 'entries': entries}
    metadata = json.dumps(manifest, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')
    if len(metadata) > MAX_MANIFEST:
        raise ValueError('manifest exceeds 4 MiB')
    result = MAGIC+struct.pack('>I', len(metadata))+metadata+b''.join(unique)
    if len(result) > MAX_ARCHIVE:
        raise ValueError('archive exceeds 16 MiB')
    return result


def _decode(archive):
    if not isinstance(archive, bytes) or not 12 <= len(archive) <= MAX_ARCHIVE or archive[:8] != MAGIC:
        raise ValueError('invalid archive header or size')
    length = struct.unpack('>I', archive[8:12])[0]
    if not 1 <= length <= MAX_MANIFEST or 12+length > len(archive):
        raise ValueError('invalid manifest length')
    try:
        meta = json.loads(archive[12:12+length], object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid manifest JSON') from exc
    _object(meta, ['version', 'config', 'chunks', 'entries'])
    _integer(meta['version'], 1, 1, 'format version')
    _object(meta['config'], ['method', 'minimum', 'maximum', 'mask_bits', 'fixed_size'])
    config = Config(**meta['config'])
    if not isinstance(meta['chunks'], list) or len(meta['chunks']) > MAX_REFERENCES:
        raise ValueError('invalid chunk table')
    if not isinstance(meta['entries'], list) or not 1 <= len(meta['entries']) <= 32:
        raise ValueError('invalid entry table')
    unique, known_hashes, cursor = [], set(), 12+length
    for spec in meta['chunks']:
        _object(spec, ['size', 'sha256'])
        size = _integer(spec['size'], 1, 65536, 'chunk size')
        _hash(spec['sha256'])
        if spec['sha256'] in known_hashes:
            raise ValueError('duplicate chunk digest')
        known_hashes.add(spec['sha256'])
        if cursor+size > len(archive):
            raise ValueError('truncated chunk payload')
        block = archive[cursor:cursor+size]
        if digest(block) != spec['sha256']:
            raise ValueError('chunk digest mismatch')
        unique.append(block)
        cursor += size
    if cursor != len(archive):
        raise ValueError('trailing archive bytes')
    versions, used = [], set()
    total_size = total_refs = 0
    for entry in meta['entries']:
        _object(entry, ['size', 'sha256', 'refs'])
        size = _integer(entry['size'], 0, MAX_BYTES, 'entry size')
        total_size += size
        if total_size > MAX_BYTES:
            raise ValueError('combined output exceeds 8 MiB')
        _hash(entry['sha256'])
        refs = entry['refs']
        if not isinstance(refs, list) or len(refs) > MAX_REFERENCES:
            raise ValueError('invalid entry references')
        total_refs += len(refs)
        if total_refs > MAX_REFERENCES:
            raise ValueError('too many chunk references')
        for index in refs:
            _integer(index, 0, len(unique)-1, 'chunk index')
        if sum(len(unique[i]) for i in refs) != size:
            raise ValueError('entry size does not match references')
        restored = b''.join(unique[i] for i in refs)
        if digest(restored) != entry['sha256']:
            raise ValueError('entry digest mismatch')
        if [len(b) for b in chunks(restored, config)] != [len(unique[i]) for i in refs]:
            raise ValueError('references violate declared chunk boundaries')
        used.update(refs)
        versions.append(restored)
    if used != set(range(len(unique))):
        raise ValueError('unreferenced stored chunks')
    stats = {'entry_count': len(versions), 'raw_bytes': total_size, 'chunk_references': total_refs,
             'unique_chunks': len(unique), 'unique_payload_bytes': sum(map(len, unique)),
             'metadata_and_header_bytes': 12+length, 'archive_bytes': len(archive),
             'payload_bytes_saved': total_size-sum(map(len, unique)), 'config': asdict(config)}
    return versions, stats


def unpack(archive):
    """Fully validate all entries and return their bytes in original order."""
    return _decode(archive)[0]


def inspect_archive(archive):
    """Report storage accounting only after full payload and boundary validation."""
    return _decode(archive)[1]
