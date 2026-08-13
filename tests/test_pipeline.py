from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import open_rar_member
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
    assert result.strategy == "zip-images"
    assert result.metadata.title == "comic"
    assert result.warnings
    with open_rar_member(output, "000001.jpg") as page:
        assert page.read() == b"\xff\xd8\xffnot-a-complete-jpeg"
