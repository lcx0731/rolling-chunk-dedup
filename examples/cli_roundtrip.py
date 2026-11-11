"""Exercise the installed command in an isolated temporary directory."""

import json
from pathlib import Path
import subprocess
import tempfile


with tempfile.TemporaryDirectory(prefix='rolling-dedup-cli-') as directory:
    root = Path(directory)
    a, b = bytes(range(256))*16, bytes(range(256))*8+b'inserted'+bytes(range(256))*8
    (root/'a.bin').write_bytes(a)
    (root/'b.bin').write_bytes(b)
    for method in ['buzhash', 'fixed']:
        path = root/f'{method}.rcd'
        subprocess.run(['rolling-dedup','pack',str(root/'a.bin'),str(root/'b.bin'),'--output',str(path),'--method',method],check=True,capture_output=True)
        report = subprocess.run(['rolling-dedup','inspect',str(path)],check=True,capture_output=True,text=True)
        for i, expected in enumerate([a,b]):
            target = root/f'{method}-{i}.bin'
            subprocess.run(['rolling-dedup','unpack',str(path),'--entry',str(i),'--output',str(target)],check=True,capture_output=True)
            assert target.read_bytes() == expected
        print(json.dumps({'method':method,'roundtrip':'exact',**json.loads(report.stdout)}))
