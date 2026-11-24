from __future__ import annotations

import io
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import ConversionError, detect_archive_format, open_rar_member
from banca_revista.batch import run_batch
from banca_revista.cbr import convert_to_cbr, count_source_pages, detect_cbr_source
from banca_revista.container import extract_container, inspect_container
from banca_revista.sevenzip import inspect_7z, open_7z_member

TOOLS = ("7z", "rar", "unrar")
needs_7z = pytest.mark.skipif(not shutil.which("7z"), reason="7z não instalado")
needs_tools = pytest.mark.skipif(not all(shutil.which(tool) for tool in TOOLS), reason="7z, rar e unrar necessários")


def _make_7z(archive: Path, files: dict[str, bytes], *options: str) -> Path:
    """Cria um 7-Zip real a partir de arquivos gravados numa pasta própria, ao lado do destino."""
    staging = archive.parent / f"{archive.name}-staging"
    for name, content in files.items():
        path = staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    subprocess.run(
        ["7z", "a", "-bd", "-y", "-ms=on", *options, os.fspath(archive.absolute()), *sorted(files)],
        cwd=staging,
        check=True,
        capture_output=True,
    )
    return archive


PAGES = {
    "volume/10.jpg": b"\xff\xd8\xffpage-10",
    "volume/2.jpg": b"\xff\xd8\xffpage-2",
    "volume/info.txt": b"scan",
}


@needs_7z
def test_signature_detects_7z_even_with_cbr_extension(tmp_path: Path) -> None:
    source = _make_7z(tmp_path / "issue.cbr", PAGES)

    assert detect_cbr_source(source) == "7z"
    assert detect_archive_format(source) == "7z"


@needs_7z
def test_inspect_7z_lists_pages_in_natural_order_without_writing(tmp_path: Path) -> None:
    source = _make_7z(tmp_path / "issue.cbr", PAGES)
    before = sorted(tmp_path.rglob("*"))

    inspection = inspect_7z(source)

    assert [page.source_name for page in inspection.pages] == ["volume/2.jpg", "volume/10.jpg"]
    assert sorted(tmp_path.rglob("*")) == before


@needs_tools
def test_convert_7z_creates_cbr_with_same_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = _make_7z(tmp_path / "issue.cbr", PAGES)
    output = tmp_path / "out" / "issue.cbr"

    result = convert_to_cbr(source, output)

    assert (result.input_format, result.strategy, result.page_count) == ("7z", "7z-normalized", 2)
    with open_rar_member(output, "000001.jpg") as first:
        assert first.read() == b"\xff\xd8\xffpage-2"
    with open_rar_member(output, "000002.jpg") as second:
        assert second.read() == b"\xff\xd8\xffpage-10"
    assert count_source_pages(source) == 2
    assert sorted(path.name for path in (tmp_path / "out").iterdir()) == ["issue.cbr"]


@needs_7z
@pytest.mark.parametrize("options", [("-psegredo",), ("-psegredo", "-mhe=on")], ids=["dados", "cabecalho"])
def test_inspect_7z_rejects_password(tmp_path: Path, options: tuple[str, ...]) -> None:
    source = _make_7z(tmp_path / "locked.cbr", PAGES, *options)

    with pytest.raises(ConversionError, match="senha"):
        inspect_7z(source)


@needs_7z
def test_inspect_7z_rejects_truncated_archive(tmp_path: Path) -> None:
    source = _make_7z(tmp_path / "issue.cbr", {"001.jpg": os.urandom(4096), "002.jpg": os.urandom(4096)}, "-mx=0")
    source.write_bytes(source.read_bytes()[:3000])

    with pytest.raises(ConversionError, match="7z"):
        inspect_7z(source)


@needs_tools
def test_convert_7z_rejects_symlinked_page(tmp_path: Path) -> None:
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"\xff\xd8\xffsecret")
    staging = tmp_path / "evil.cbr-staging"
    staging.mkdir()
    (staging / "001.jpg").write_bytes(b"\xff\xd8\xffok")
    (staging / "002.jpg").symlink_to(secret)
    subprocess.run(
        ["7z", "a", "-bd", "-snl", os.fspath(tmp_path / "evil.cbr"), "001.jpg", "002.jpg"],
        cwd=staging,
        check=True,
        capture_output=True,
    )

    with pytest.raises(ConversionError, match="link"):
        convert_to_cbr(tmp_path / "evil.cbr", tmp_path / "out" / "evil.cbr")
    assert not (tmp_path / "out" / "evil.cbr").exists()


@needs_7z
def test_7z_container_extracts_comics(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as comic:
        comic.writestr("001.jpg", b"\xff\xd8\xffcbz")
    source = _make_7z(tmp_path / "pack.7z", {"serie/A 01.cbz": buffer.getvalue()})
    destination = tmp_path / "dest"
    destination.mkdir()

    container = inspect_container(source)
    assert container is not None and container.archive_format == "7z"
    (extracted,) = extract_container(container, destination)

    assert extracted.path == destination / "A 01.cbz"
    assert extracted.path.read_bytes() == buffer.getvalue()


@needs_tools
def test_batch_converts_zip_holding_7z_disguised_as_cbr(tmp_path: Path) -> None:
    base = tmp_path / "source"
    base.mkdir()
    inner = _make_7z(tmp_path / "TMNT 01.cbr", {"p/001.jpg": b"\xff\xd8\xff01a", "p/002.jpg": b"\xff\xd8\xff01b"})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as comic:
        comic.writestr("001.jpg", b"\xff\xd8\xff02")
    with zipfile.ZipFile(base / "TMNT.zip", "w") as pack:
        pack.write(inner, "TMNT 01.cbr")
        pack.writestr("TMNT 02.cbr", buffer.getvalue())
    output = tmp_path / "output"
    trash = tmp_path / "Trash"

    report = run_batch(
        base, output, dry_run=False, lookup_isbn=False, workers=2, remove_originals=True, trash_dir=trash
    )

    assert [(item.source.name, item.status, item.source_removed) for item in report.items] == [
        ("TMNT 01.cbr", "processed", True),
        ("TMNT 02.cbr", "processed", True),
        ("TMNT.zip", "extracted", True),
    ]
    assert "2 páginas" in (report.items[0].detail or "")
    assert sorted(path.name for path in output.glob("*.cbr")) == ["TMNT 01.cbr", "TMNT 02.cbr"]
    assert list(base.iterdir()) == []


@needs_7z
def test_inspect_7z_rejects_symlink_before_extracting(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "001.jpg").write_bytes(b"\xff\xd8\xffok")
    (staging / "fora").symlink_to(tmp_path)
    subprocess.run(
        ["7z", "a", "-bd", "-snl", os.fspath(tmp_path / "evil.cbr"), "001.jpg", "fora"],
        cwd=staging,
        check=True,
        capture_output=True,
    )

    with pytest.raises(ConversionError, match="link simbólico"):
        inspect_7z(tmp_path / "evil.cbr")


@needs_7z
def test_open_7z_member_treats_at_sign_name_literally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Depois de ``--`` o 7z não lê ``@nome`` como lista de arquivos (conferido no 7-Zip 26.04)."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "@lista.cbz").write_bytes(b"arroba")
    (staging / "a.cbz").write_bytes(b"isca")
    (tmp_path / "names.txt").write_text("@lista.cbz\na.cbz\n")
    subprocess.run(["7z", "a", "-bd", "../pack.7z", "@../names.txt"], cwd=staging, check=True, capture_output=True)
    (tmp_path / "lista.cbz").write_text("a.cbz\n")
    monkeypatch.chdir(tmp_path)

    with open_7z_member(tmp_path / "pack.7z", "@lista.cbz") as member:
        assert member.read() == b"arroba"
