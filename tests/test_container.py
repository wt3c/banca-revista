from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import ConversionError
from banca_revista.cbr import convert_to_cbr
from banca_revista.container import extract_container, find_comic_entries, inspect_container

# "Há" com "a" cirílico (U+0430), como no ZIP real do Wolverine.
HA = "H\u0430"

requires_rar = pytest.mark.skipif(
    not shutil.which("rar") or not shutil.which("unrar"), reason="rar e unrar não instalados"
)


def _cbz_bytes(page: bytes = b"\xff\xd8\xffpage") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("001.jpg", page)
    return buffer.getvalue()


def _write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_find_comic_entries_sorts_naturally_and_ignores_extras() -> None:
    names = ["serie/issue 10.cbr", "serie/issue 2.CBZ", "serie/issue 1.pdf", "serie/", "info.txt", "__MACOSX/x.cbr"]

    assert find_comic_entries(names) == ("serie/issue 1.pdf", "serie/issue 2.CBZ", "serie/issue 10.cbr")


def test_find_comic_entries_returns_empty_for_image_archive() -> None:
    assert find_comic_entries(["001.jpg", "002.png", "ComicInfo.xml"]) == ()


def test_find_comic_entries_treats_images_with_extra_comic_as_regular_archive() -> None:
    assert find_comic_entries(["001.jpg", "creditos.pdf", "creditos.cbr"]) == ()


@pytest.mark.parametrize(
    ("names", "message"),
    [
        (["../issue.cbr"], "insegura"),
        (["/abs/issue.cbr"], "insegura"),
        (["a/Issue.cbr", "b/issue.CBR"], "mesma saída"),
    ],
)
def test_find_comic_entries_rejects_ambiguous_or_unsafe_names(names: list[str], message: str) -> None:
    with pytest.raises(ConversionError, match=message):
        find_comic_entries(names)


def test_inspect_container_returns_none_for_image_zip(tmp_path: Path) -> None:
    source = _write_zip(tmp_path / "comic.zip", {"001.jpg": b"\xff\xd8\xffpage"})

    assert inspect_container(source) is None


def test_inspect_container_lists_comics_inside_zip_without_writing(tmp_path: Path) -> None:
    source = _write_zip(
        tmp_path / "Rainha.zip",
        {"[X]Rainha_02.cbz": _cbz_bytes(), "[X]Rainha_01.cbz": _cbz_bytes(), "leia.txt": b"x"},
    )

    inspection = inspect_container(source)

    assert inspection is not None
    assert inspection.archive_format == "zip"
    assert inspection.members == ("[X]Rainha_01.cbz", "[X]Rainha_02.cbz")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Rainha.zip"]


def test_extract_zip_container_writes_each_comic_next_to_source(tmp_path: Path) -> None:
    pdf = b"%PDF-1.4 issue 1"
    cbz = _cbz_bytes()
    source = _write_zip(tmp_path / "Wolverine.zip", {f"w/{HA} #01.pdf": pdf, f"w/{HA} #02.cbz": cbz})
    original_hash = _sha256(source)
    inspection = inspect_container(source)
    assert inspection is not None

    extracted = extract_container(inspection, tmp_path)

    assert [(item.member, item.path.name, item.reused) for item in extracted] == [
        (f"w/{HA} #01.pdf", f"{HA} #01.pdf", False),
        (f"w/{HA} #02.cbz", f"{HA} #02.cbz", False),
    ]
    assert (tmp_path / f"{HA} #01.pdf").read_bytes() == pdf
    assert (tmp_path / f"{HA} #02.cbz").read_bytes() == cbz
    assert _sha256(source) == original_hash
    assert sorted(path.name for path in tmp_path.iterdir()) == [f"{HA} #01.pdf", f"{HA} #02.cbz", "Wolverine.zip"]


def test_extract_container_reuses_identical_file_and_never_overwrites(tmp_path: Path) -> None:
    source = _write_zip(tmp_path / "pack.zip", {"a.cbz": _cbz_bytes(b"\xff\xd8\xffa"), "b.cbz": _cbz_bytes()})
    inspection = inspect_container(source)
    assert inspection is not None
    extract_container(inspection, tmp_path)

    again = extract_container(inspection, tmp_path)

    assert [item.reused for item in again] == [True, True]

    different = tmp_path / "b.cbz"
    different.write_bytes(_cbz_bytes(b"\xff\xd8\xffoutra"))
    before = _sha256(different)
    with pytest.raises(ConversionError, match="já existe com conteúdo diferente"):
        extract_container(inspection, tmp_path)
    assert _sha256(different) == before
    assert not list(tmp_path.glob(".banca-*"))


def test_extract_container_rejects_member_with_wrong_content(tmp_path: Path) -> None:
    source = _write_zip(tmp_path / "pack.zip", {"fake.pdf": b"not a pdf"})
    inspection = inspect_container(source)
    assert inspection is not None

    with pytest.raises(ConversionError, match="não é PDF"):
        extract_container(inspection, tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pack.zip"]


@requires_rar
def test_inspect_and_extract_rar_container(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "issue 2.cbz").write_bytes(_cbz_bytes(b"\xff\xd8\xff2"))
    (staging / "issue 1.pdf").write_bytes(b"%PDF-1.4 um")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "pack.rar"
    subprocess.run(
        ["rar", "a", "-idq", "-ep1", "--", str(source), str(staging / "issue 2.cbz"), str(staging / "issue 1.pdf")],
        check=True,
    )

    inspection = inspect_container(source)
    assert inspection is not None
    assert inspection.archive_format == "rar"
    assert inspection.members == ("issue 1.pdf", "issue 2.cbz")

    extract_container(inspection, source_dir)

    assert (source_dir / "issue 1.pdf").read_bytes() == b"%PDF-1.4 um"
    assert (source_dir / "issue 2.cbz").read_bytes() == (staging / "issue 2.cbz").read_bytes()


def test_find_comic_entries_rejects_members_that_share_output_name() -> None:
    with pytest.raises(ConversionError, match="mesma saída"):
        find_comic_entries(["edicao.pdf", "Edicao.cbz"])


def test_extract_zip_with_unsupported_compression_raises_conversion_error(tmp_path: Path) -> None:
    source = _write_zip(tmp_path / "pack.zip", {"issue.cbz": _cbz_bytes()})
    data = bytearray(source.read_bytes())
    # O CBZ interno também tem cabeçalhos ZIP: o local externo é o primeiro e o central externo, o último.
    for position in (data.index(b"PK\x03\x04") + 8, data.rindex(b"PK\x01\x02") + 10):
        data[position : position + 2] = (99).to_bytes(2, "little")
    source.write_bytes(bytes(data))
    inspection = inspect_container(source)
    assert inspection is not None

    with pytest.raises(ConversionError, match=r"issue\.cbz"):
        extract_container(inspection, tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["pack.zip"]


@requires_rar
def test_extract_corrupted_rar_member_publishes_nothing(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    payload = _cbz_bytes(b"\xff\xd8\xff" + bytes(range(256)) * 64)
    (staging / "issue.cbz").write_bytes(payload)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "pack.rar"
    subprocess.run(["rar", "a", "-idq", "-m0", "-ep1", "--", str(source), str(staging / "issue.cbz")], check=True)
    data = bytearray(source.read_bytes())
    middle = data.index(payload) + len(payload) // 2
    data[middle] ^= 0xFF
    source.write_bytes(bytes(data))
    inspection = inspect_container(source)
    assert inspection is not None

    with pytest.raises(ConversionError):
        extract_container(inspection, source_dir)
    assert sorted(path.name for path in source_dir.iterdir()) == ["pack.rar"]


@requires_rar
def test_convert_rar_with_images_and_extra_pdf_keeps_previous_behavior(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "001.jpg").write_bytes(b"\xff\xd8\xffpage")
    (staging / "creditos.pdf").write_bytes(b"%PDF-1.4")
    source = tmp_path / "comic.cbr"
    subprocess.run(["rar", "a", "-idq", "-ep1", "--", str(source), *map(str, staging.iterdir())], check=True)

    result = convert_to_cbr(source, tmp_path / "out" / "comic.cbr")

    assert result.page_count == 1
