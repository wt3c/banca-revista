from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import (
    ArchiveInspection,
    ConversionError,
    convert_rar_to_cbz,
    detect_archive_format,
    plan_pages,
)


def test_detect_archive_format_uses_content_instead_of_extension(tmp_path: Path) -> None:
    disguised_rar = tmp_path / "comic.zip"
    disguised_rar.write_bytes(b"Rar!\x1a\x07\x01\x00payload")

    assert detect_archive_format(disguised_rar) == "rar"


def test_plan_pages_flattens_and_sorts_naturally() -> None:
    pages, common_parent = plan_pages(["volume/(10).jpg", "volume/(2).jpg", "volume/(000).jpg", "volume"])

    assert [page.output_name for page in pages] == ["(000).jpg", "(2).jpg", "(10).jpg"]
    assert common_parent == "volume"


@pytest.mark.parametrize("unsafe_name", ["../cover.jpg", "/cover.jpg", "volume/../../cover.jpg"])
def test_plan_pages_rejects_unsafe_paths(unsafe_name: str) -> None:
    with pytest.raises(ConversionError, match="entrada insegura"):
        plan_pages([unsafe_name])


def test_plan_pages_rejects_collisions_after_flattening() -> None:
    with pytest.raises(ConversionError, match="colidem"):
        plan_pages(["chapter-a/001.jpg", "chapter-b/001.JPG"])


def test_plan_pages_allows_repeated_names_when_paths_are_preserved() -> None:
    pages, common_parent = plan_pages(
        ["issue 10/001.jpg", "issue 2/001.jpg", "issue 1/001.jpg"],
        flatten=False,
    )

    assert [page.output_name for page in pages] == [
        "issue 1/001.jpg",
        "issue 2/001.jpg",
        "issue 10/001.jpg",
    ]
    assert common_parent is None


def test_convert_creates_valid_flat_cbz_and_preserves_bytes(tmp_path: Path) -> None:
    source = tmp_path / "original.cbr"
    source.write_bytes(b"Rar!\x1a\x07\x01\x00test")
    pages, common_parent = plan_pages(["volume/010.jpg", "volume/002.jpg", "volume/001.jpg"])
    inspection = ArchiveInspection(source=source, archive_format="rar", pages=pages, common_parent=common_parent)
    contents = {
        "volume/001.jpg": b"first-page",
        "volume/002.jpg": b"second-page",
        "volume/010.jpg": b"tenth-page",
    }

    def extract_member(_source: Path, name: str) -> io.BytesIO:
        return io.BytesIO(contents[name])

    output = tmp_path / "normalized.cbz"
    result = convert_rar_to_cbz(inspection, output, extractor=extract_member)

    assert result.page_count == 3
    assert result.first_page == "001.jpg"
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["001.jpg", "002.jpg", "010.jpg"]
        assert all("/" not in name for name in archive.namelist())
        assert archive.testzip() is None
        for source_name, expected in contents.items():
            output_name = Path(source_name).name
            assert archive.read(output_name) == expected
            assert result.sha256_by_page[output_name] == hashlib.sha256(expected).hexdigest()


def test_convert_does_not_overwrite_existing_output(tmp_path: Path) -> None:
    source = tmp_path / "original.cbr"
    source.write_bytes(b"Rar!\x1a\x07\x01\x00test")
    pages, common_parent = plan_pages(["volume/001.jpg"])
    inspection = ArchiveInspection(source=source, archive_format="rar", pages=pages, common_parent=common_parent)
    output = tmp_path / "normalized.cbz"
    output.write_bytes(b"keep-me")

    with pytest.raises(ConversionError, match="já existe"):
        convert_rar_to_cbz(inspection, output, extractor=lambda _source, _name: io.BytesIO(b"page"))

    assert output.read_bytes() == b"keep-me"


def test_convert_removes_temporary_output_after_failure(tmp_path: Path) -> None:
    source = tmp_path / "original.cbr"
    source.write_bytes(b"Rar!\x1a\x07\x01\x00test")
    pages, common_parent = plan_pages(["volume/001.jpg"])
    inspection = ArchiveInspection(source=source, archive_format="rar", pages=pages, common_parent=common_parent)
    output = tmp_path / "normalized.cbz"

    def fail_extraction(_source: Path, _name: str) -> io.BytesIO:
        raise ConversionError("falha simulada")

    with pytest.raises(ConversionError, match="falha simulada"):
        convert_rar_to_cbz(inspection, output, extractor=fail_extraction)

    assert not output.exists()
    assert list(tmp_path.glob(".normalized.cbz.*.tmp")) == []
