"""A 64-bit Buzhash rolling window, independent of chunk-boundary state."""

from dataclasses import dataclass
import hashlib


WINDOW = 31
MASK64 = (1 << 64)-1
MAX_BYTES = 8*1024*1024
# Public deterministic table; part of format version 1, not a secret key.
TABLE = tuple(int.from_bytes(hashlib.sha256(b'rolling-chunk-dedup-v1:'+bytes([b])).digest()[:8], 'big') for b in range(256))


def rotate(value, count):
    count %= 64
    return ((value << count) | (value >> ((64-count) % 64))) & MASK64


@dataclass(frozen=True)
class Config:
    method: str = 'buzhash'
    minimum: int = 256
    maximum: int = 4096
    mask_bits: int = 10
    fixed_size: int = 1024

    def __post_init__(self):
        if self.method not in ('buzhash', 'fixed'):
            raise ValueError('method must be buzhash or fixed')
        for name, low, high in [('minimum', 32, 65536), ('maximum', 32, 65536), ('mask_bits', 5, 16), ('fixed_size', 32, 65536)]:
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} must be an integer from {low} to {high}')
        if self.minimum > self.maximum:
            raise ValueError('minimum cannot exceed maximum')


def _bytes(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError('data must be bytes of length at most 8 MiB')


def rolling_hashes(data):
    """Hash each prefix's last min(31, prefix length) bytes in O(n) updates."""
    _bytes(data)
    state = 0
    for i, incoming in enumerate(data):
        state = rotate(state, 1) ^ TABLE[incoming]
        if i >= WINDOW:
            state ^= rotate(TABLE[data[i-WINDOW]], WINDOW)
        yield state


def spans(data, config=Config()):
    """Return half-open boundaries; only the final chunk can be below minimum."""
    _bytes(data)
    if not isinstance(config, Config):
        raise ValueError('config must be a Config object')
    if config.method == 'fixed':
        return [(i, min(len(data), i+config.fixed_size)) for i in range(0, len(data), config.fixed_size)]
    out, start = [], 0
    mask = (1 << config.mask_bits)-1
    for i, fingerprint in enumerate(rolling_hashes(data), 1):
        age = i-start
        if age >= config.maximum or (age >= config.minimum and fingerprint & mask == 0):
            out.append((start, i))
            start = i
    if start < len(data):
        out.append((start, len(data)))
    return out


def chunks(data, config=Config()):
    return [data[a:b] for a, b in spans(data, config)]
