"""Pack, inspect, or extract one entry; outputs are new files, never overwritten."""

import argparse
import json
from pathlib import Path
import sys

from .archive import MAX_ARCHIVE, inspect_archive, pack, unpack
from .chunker import MAX_BYTES, Config


def _read(path, limit):
    with path.open('rb') as handle:
        data = handle.read(limit+1)
    if len(data) > limit:
        raise ValueError('file exceeds size limit')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    packing = sub.add_parser('pack')
    packing.add_argument('inputs', nargs='+', type=Path)
    packing.add_argument('--output', required=True, type=Path)
    packing.add_argument('--method', choices=['buzhash', 'fixed'], default='buzhash')
    packing.add_argument('--fixed-size', type=int, default=1024)
    inspection = sub.add_parser('inspect')
    inspection.add_argument('archive', type=Path)
    extracting = sub.add_parser('unpack')
    extracting.add_argument('archive', type=Path)
    extracting.add_argument('--entry', required=True, type=int)
    extracting.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'pack':
            if len(args.inputs) > 32:
                raise ValueError('at most 32 input files')
            versions, size = [], 0
            for path in args.inputs:
                data = _read(path, MAX_BYTES-size)
                versions.append(data)
                size += len(data)
            archive = pack(versions, Config(method=args.method, fixed_size=args.fixed_size))
            report = inspect_archive(archive)
            with args.output.open('xb') as handle:
                handle.write(archive)
            print(json.dumps(report, indent=2))
        elif args.command == 'inspect':
            print(json.dumps(inspect_archive(_read(args.archive, MAX_ARCHIVE)), indent=2))
        else:
            entries = unpack(_read(args.archive, MAX_ARCHIVE))
            if not 0 <= args.entry < len(entries):
                raise ValueError('entry index out of range')
            with args.output.open('xb') as handle:
                handle.write(entries[args.entry])
            print(json.dumps({'entry': args.entry, 'restored_bytes': len(entries[args.entry])}))
    except (OSError, ValueError, TypeError) as exc:
        print(f'rolling-dedup: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
