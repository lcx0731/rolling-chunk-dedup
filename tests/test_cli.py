import json

from rolling_dedup.cli import main


def test_cli_roundtrip_without_overwrite(tmp_path, capsys):
    source = tmp_path/'source.bin'
    archive = tmp_path/'archive.rcd'
    restored = tmp_path/'restored.bin'
    data = bytes(range(256))*20
    source.write_bytes(data)
    assert main(['pack',str(source),'--output',str(archive)]) == 0
    original_archive = archive.read_bytes()
    assert main(['inspect',str(archive)]) == 0
    capsys.readouterr()
    assert main(['unpack',str(archive),'--entry','0','--output',str(restored)]) == 0
    assert json.loads(capsys.readouterr().out)['restored_bytes'] == len(data)
    assert restored.read_bytes() == source.read_bytes() == data
    assert main(['pack',str(source),'--output',str(archive)]) == 1
    assert archive.read_bytes() == original_archive
    assert main(['unpack',str(archive),'--entry','0','--output',str(restored)]) == 1
    assert restored.read_bytes() == data


def test_invalid_archive_never_creates_output(tmp_path, capsys):
    damaged = tmp_path/'bad.rcd'
    target = tmp_path/'output'
    damaged.write_bytes(b'invalid')
    assert main(['unpack',str(damaged),'--entry','0','--output',str(target)]) == 1
    assert not target.exists()
    assert capsys.readouterr().err.startswith('rolling-dedup:')


def test_invalid_entry_never_creates_output(tmp_path, capsys):
    source, archive, target = (tmp_path/n for n in ['source','archive','out'])
    source.write_bytes(b'abc')
    assert main(['pack',str(source),'--output',str(archive)]) == 0
    assert main(['unpack',str(archive),'--entry','-1','--output',str(target)]) == 1
    assert not target.exists()


def test_missing_file(tmp_path, capsys):
    assert main(['inspect',str(tmp_path/'missing')]) == 1
    assert capsys.readouterr().err.startswith('rolling-dedup:')
