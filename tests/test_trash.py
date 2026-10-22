from __future__ import annotations

from pathlib import Path

import pytest

from banca_revista.trash import move_to_trash


def test_move_to_trash_keeps_restorable_info(tmp_path: Path) -> None:
    source = tmp_path / "origem" / "Jonah Hex 01 #1.cbr"
    source.parent.mkdir()
    source.write_bytes(b"Rar!conteudo")
    trash = tmp_path / "Trash"

    target = move_to_trash(source, trash)

    assert not source.exists()
    assert target == trash / "files" / "Jonah Hex 01 #1.cbr"
    assert target.read_bytes() == b"Rar!conteudo"
    info = (trash / "info" / "Jonah Hex 01 #1.cbr.trashinfo").read_text(encoding="utf-8").splitlines()
    assert info[0] == "[Trash Info]"
    assert info[1] == f"Path={source.parent.as_posix()}/Jonah%20Hex%2001%20%231.cbr"
    assert info[2].startswith("DeletionDate=")


def test_move_to_trash_never_overwrites_existing_trash_entry(tmp_path: Path) -> None:
    trash = tmp_path / "Trash"
    first = tmp_path / "a" / "issue.cbz"
    second = tmp_path / "b" / "issue.cbz"
    for path, content in ((first, b"1"), (second, b"2")):
        path.parent.mkdir()
        path.write_bytes(content)

    move_to_trash(first, trash)
    target = move_to_trash(second, trash)

    assert target == trash / "files" / "issue.2.cbz"
    assert (trash / "files" / "issue.cbz").read_bytes() == b"1"
    assert target.read_bytes() == b"2"
    assert (trash / "info" / "issue.2.cbz.trashinfo").exists()


def test_move_to_trash_refuses_missing_file_without_leaving_info(tmp_path: Path) -> None:
    trash = tmp_path / "Trash"

    with pytest.raises(OSError):
        move_to_trash(tmp_path / "ausente.cbr", trash)
    assert not trash.exists()
