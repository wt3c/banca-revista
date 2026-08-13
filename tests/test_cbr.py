from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import ConversionError, open_rar_member
from banca_revista.cbr import PdfImage, classify_zip_entries, convert_to_cbr, detect_cbr_source, pdf_lossless_eligible


def test_detect_cbr_source_uses_signature(tmp_path: Path) -> None:
    pdf = tmp_path / "disguised.zip"
    pdf.write_bytes(b"%PDF-1.4\n")

    assert detect_cbr_source(pdf) == "pdf"


def test_classify_zip_images_sorts_naturally() -> None:
    mode, entries = classify_zip_entries(["volume/10.jpg", "volume/2.jpg", "volume/1.jpg", "ComicInfo.xml"])

    assert mode == "images"
    assert entries == ("volume/1.jpg", "volume/2.jpg", "volume/10.jpg")


def test_classify_zip_nested_cbr_sorts_issues() -> None:
    mode, entries = classify_zip_entries(["series/issue 10.cbr", "series/issue 2.cbr", "series/issue 1.cbr"])

    assert mode == "nested-cbr"
    assert entries == ("series/issue 1.cbr", "series/issue 2.cbr", "series/issue 10.cbr")


@pytest.mark.parametrize("names", [["../cover.jpg"], ["cover.jpg", "issue.cbr"], ["document.pdf"]])
def test_classify_zip_rejects_unsafe_or_ambiguous_content(names: list[str]) -> None:
    with pytest.raises(ConversionError):
        classify_zip_entries(names)


def test_pdf_lossless_requires_one_jpeg_per_page() -> None:
    images = (
        PdfImage(page=1, image_type="image", encoding="jpeg"),
        PdfImage(page=2, image_type="image", encoding="jpeg"),
    )

    assert pdf_lossless_eligible(2, images)
    assert not pdf_lossless_eligible(3, images)
    assert not pdf_lossless_eligible(2, (*images, PdfImage(page=2, image_type="smask", encoding="image")))


@pytest.mark.skipif(not shutil.which("rar") or not shutil.which("unrar"), reason="rar e unrar não instalados")
def test_convert_zip_images_creates_true_cbr_in_natural_order(tmp_path: Path) -> None:
    source = tmp_path / "comic.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("volume/10.jpg", b"\xff\xd8\xffpage-10")
        archive.writestr("volume/2.jpg", b"\xff\xd8\xffpage-2")
    output = tmp_path / "comic.cbr"

    result = convert_to_cbr(source, output)

    assert result.input_format == "zip"
    assert result.strategy == "zip-images"
    assert result.page_count == 2
    with open_rar_member(output, "000001.jpg") as first:
        assert first.read() == b"\xff\xd8\xffpage-2"
    with open_rar_member(output, "000002.jpg") as second:
        assert second.read() == b"\xff\xd8\xffpage-10"
