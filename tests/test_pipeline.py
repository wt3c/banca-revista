from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import open_rar_member
from banca_revista.cbr import CbrConversionResult
from banca_revista.ocr import MetadataCandidate, OcrReport, PageOcr
from banca_revista.pipeline import process_to_library


@pytest.mark.skipif(not shutil.which("rar") or not shutil.which("unrar"), reason="rar e unrar não instalados")
def test_pipeline_publishes_even_when_ocr_cannot_read_page(tmp_path: Path) -> None:
    source = tmp_path / "comic.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("001.jpg", b"\xff\xd8\xffnot-a-complete-jpeg")
    output = tmp_path / "library" / "comic.cbr"

    result = process_to_library(source, output, lookup_isbn=False)

    assert result.output == output
    assert result.page_count == 1
    assert result.first_page == "000001.jpg"
    assert result.strategy == "zip-images"
    assert result.metadata.title == "comic"
    assert result.warnings
    password_probe = subprocess.run(
        ["unrar", "t", "-idq", "-pwrong-password", "--", str(output)],
        check=False,
        capture_output=True,
    )
    assert password_probe.returncode == 0
    with open_rar_member(output, "000001.jpg") as page:
        assert page.read() == b"\xff\xd8\xffnot-a-complete-jpeg"


def test_pipeline_reports_when_first_two_pages_have_no_isbn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "comic.cbr"
    source.write_bytes(b"source")
    output = tmp_path / "library" / "comic.cbr"

    def fake_convert(original: Path, normalized: Path) -> CbrConversionResult:
        normalized.write_bytes(original.read_bytes())
        return CbrConversionResult(original, normalized, "rar", 2, "000001.jpg", "cbr-normalized")

    report = OcrReport(
        source=source,
        pages=(PageOcr("000001.jpg", "capa"), PageOcr("000002.jpg", "página")),
        candidates=(MetadataCandidate("title", "Comic", 0.98, "nome do arquivo"),),
    )

    def fake_create_metadata(normalized: Path, enriched: Path, _metadata: object) -> Path:
        enriched.write_bytes(normalized.read_bytes())
        return enriched

    monkeypatch.setattr("banca_revista.pipeline.convert_to_cbr", fake_convert)
    monkeypatch.setattr("banca_revista.pipeline._read_metadata", lambda _path: None)
    monkeypatch.setattr("banca_revista.pipeline.analyze_cbr", lambda *_args, **_kwargs: report)
    monkeypatch.setattr("banca_revista.pipeline.create_metadata_cbr", fake_create_metadata)

    result = process_to_library(source, output)

    assert result.warnings == ("ISBN não encontrado nas 2 primeiras páginas",)
