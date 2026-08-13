from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import ConversionError
from banca_revista.batch import BatchProgressEvent, next_report_path, plan_batch, run_batch, save_report


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


def test_batch_emits_planning_event_during_dry_run(tmp_path: Path) -> None:
    (tmp_path / "issue.pdf").write_bytes(b"%PDF-1.4")
    events: list[BatchProgressEvent] = []

    run_batch(tmp_path, tmp_path / "output", progress_callback=events.append)

    assert len(events) == 1
    assert events[0].kind == "planned"
    assert events[0].total == 1
    assert events[0].items[0].source.name == "issue.pdf"


@pytest.mark.parametrize("workers", [0, 65])
def test_batch_rejects_invalid_worker_count(tmp_path: Path, workers: int) -> None:
    with pytest.raises(ConversionError, match="workers deve estar entre 1 e 64"):
        run_batch(tmp_path, tmp_path / "output", workers=workers)


def test_batch_rejects_output_name_collision(tmp_path: Path) -> None:
    (tmp_path / "same.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "same.zip").write_bytes(b"PK\x03\x04")

    with pytest.raises(ConversionError, match="mesma saída"):
        plan_batch(tmp_path, tmp_path / "output")


def test_batch_detects_supported_inputs_by_content(tmp_path: Path) -> None:
    (tmp_path / "comic.bin").write_bytes(b"Rar!\x1a\x07\x01\x00payload")
    (tmp_path / "scan.data").write_bytes(b"%PDF-1.4")
    (tmp_path / "notes.txt").write_text("não é um quadrinho")

    items = plan_batch(tmp_path, tmp_path / "output")

    assert [(item.source.name, item.phase, item.status) for item in items] == [
        ("comic.bin", "convert", "planned"),
        ("notes.txt", "unsupported", "unsupported"),
        ("scan.data", "convert", "planned"),
    ]


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

    events: list[BatchProgressEvent] = []
    report = run_batch(
        source,
        output,
        dry_run=False,
        lookup_isbn=False,
        workers=2,
        progress_callback=events.append,
    )

    assert report.workers == 2
    assert [item.status for item in report.items] == ["processed", "processed"]
    assert [item.metadata.title for item in report.items if item.metadata] == ["issue 1", "issue 2"]
    assert [item["metadata"]["title"] for item in json.loads(report.to_json())["items"]] == ["issue 1", "issue 2"]
    assert sorted(path.name for path in output.glob("*.cbr")) == ["issue 1.cbr", "issue 2.cbr"]
    started = [event for event in events if event.kind == "started"]
    assert len(started) == 2
    assert all(event.worker_id is not None for event in started)
    assert {event.kind for event in events} == {"planned", "started", "stage", "completed"}
    assert {event.stage for event in events if event.kind == "stage"} == {
        "🔄 Normalizando para RAR 5",
        "🔎 Lendo capa, OCR e ISBN",
        "📝 Metadados e validação final",
        "📤 Publicando na biblioteca",
    }


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("rar", "unrar", "tesseract", "magick")),
    reason="ferramentas externas não instaladas",
)
def test_batch_replaces_existing_output_only_when_requested(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with zipfile.ZipFile(source / "issue.zip", "w") as archive:
        archive.writestr("001.jpg", b"\xff\xd8\xffpage")
    output = tmp_path / "output"
    output.mkdir()
    existing = output / "issue.cbr"
    existing.write_bytes(b"old")

    skipped = run_batch(source, output, dry_run=False, lookup_isbn=False, workers=1)
    replaced = run_batch(
        source,
        output,
        dry_run=False,
        lookup_isbn=False,
        workers=1,
        replace_existing=True,
    )

    assert skipped.items[0].status == "skipped"
    assert replaced.items[0].status == "processed"
    assert existing.read_bytes().startswith(b"Rar!")
