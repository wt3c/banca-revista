from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import ConversionError
from banca_revista.batch import next_report_path, plan_batch, run_batch, save_report


def test_batch_is_dry_run_by_default_and_does_not_create_output(tmp_path: Path) -> None:
    base = tmp_path / "source"
    base.mkdir()
    (base / "issue 10.pdf").write_bytes(b"%PDF-1.4")
    (base / "issue 2.zip").write_bytes(b"PK\x03\x04")
    output = tmp_path / "output"

    report = run_batch(base, output)

    assert report.dry_run
    assert report.workers == 10
    assert [item.source.name for item in report.items] == ["issue 2.zip", "issue 10.pdf"]
    assert all(item.status == "planned" for item in report.items)
    assert not output.exists()


@pytest.mark.parametrize("workers", [0, 65])
def test_batch_rejects_invalid_worker_count(tmp_path: Path, workers: int) -> None:
    with pytest.raises(ConversionError, match="workers deve estar entre 1 e 64"):
        run_batch(tmp_path, tmp_path / "output", workers=workers)


def test_batch_rejects_output_name_collision(tmp_path: Path) -> None:
    (tmp_path / "same.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "same.zip").write_bytes(b"PK\x03\x04")

    with pytest.raises(ConversionError, match="mesma saída"):
        plan_batch(tmp_path, tmp_path / "output")


def test_save_report_does_not_overwrite(tmp_path: Path) -> None:
    report = run_batch(tmp_path, tmp_path / "output")
    destination = tmp_path / "report.json"

    save_report(report, destination)

    assert json.loads(destination.read_text())["dry_run"] is True
    with pytest.raises(ConversionError, match="já existe"):
        save_report(report, destination)


def test_next_report_path_preserves_previous_reports(tmp_path: Path) -> None:
    (tmp_path / "conversion-report.json").write_text("first")
    (tmp_path / "conversion-report-2.json").write_text("second")

    assert next_report_path(tmp_path) == tmp_path / "conversion-report-3.json"


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("rar", "unrar", "tesseract", "magick")),
    reason="ferramentas externas não instaladas",
)
def test_batch_executes_items_in_process_pool(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for issue in (1, 2):
        with zipfile.ZipFile(source / f"issue {issue}.zip", "w") as archive:
            archive.writestr("001.jpg", b"\xff\xd8\xffpage")
    output = tmp_path / "output"

    report = run_batch(source, output, dry_run=False, lookup_isbn=False, workers=2)

    assert report.workers == 2
    assert [item.status for item in report.items] == ["processed", "processed"]
    assert sorted(path.name for path in output.glob("*.cbr")) == ["issue 1.cbr", "issue 2.cbr"]
