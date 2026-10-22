from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from banca_revista.archive import ConversionError
from banca_revista.batch import (
    BatchItem,
    BatchProgressEvent,
    next_report_path,
    plan_batch,
    remove_published_originals,
    run_batch,
    save_report,
)


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


def _write_comic_container(path: Path, issues: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as container:
        for issue in issues:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as comic:
                comic.writestr("001.jpg", f"\xff\xd8\xff{issue}".encode("latin-1"))
            container.writestr(f"serie/{issue}.cbz", buffer.getvalue())


def test_batch_dry_run_plans_container_extraction_without_writing(tmp_path: Path) -> None:
    base = tmp_path / "source"
    base.mkdir()
    _write_comic_container(base / "Rainha.zip", ["Rainha 02", "Rainha 01"])

    report = run_batch(base, tmp_path / "output")

    assert [(item.source.name, item.phase, item.status) for item in report.items] == [
        ("Rainha.zip", "extract", "planned")
    ]
    assert report.items[0].output == base
    assert "Rainha 01.cbz" in (report.items[0].detail or "")
    assert sorted(path.name for path in base.iterdir()) == ["Rainha.zip"]


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("rar", "unrar", "tesseract", "magick")),
    reason="ferramentas externas não instaladas",
)
def test_batch_extracts_container_then_converts_each_comic(tmp_path: Path) -> None:
    base = tmp_path / "source"
    base.mkdir()
    _write_comic_container(base / "Rainha.zip", ["Rainha 01", "Rainha 02"])
    output = tmp_path / "output"

    report = run_batch(base, output, dry_run=False, lookup_isbn=False, workers=2)

    assert [(item.source.name, item.phase, item.status) for item in report.items] == [
        ("Rainha 01.cbz", "convert", "processed"),
        ("Rainha 02.cbz", "convert", "processed"),
        ("Rainha.zip", "extract", "extracted"),
    ]
    assert sorted(path.name for path in output.glob("*.cbr")) == ["Rainha 01.cbr", "Rainha 02.cbr"]

    again = run_batch(base, output, dry_run=False, lookup_isbn=False, workers=2)

    assert [item.status for item in again.items] == ["skipped", "skipped", "extracted"]
    assert "2 já existiam" in (again.items[2].detail or "")


def test_batch_fails_only_container_whose_comic_collides_with_existing_output(tmp_path: Path) -> None:
    base = tmp_path / "source"
    base.mkdir()
    _write_comic_container(base / "pack.zip", ["Edicao 01"])
    (base / "Edicao 01.pdf").write_bytes(b"%PDF-1.4")

    report = run_batch(base, tmp_path / "output", dry_run=False, lookup_isbn=False, workers=1)

    by_name = {item.source.name: item for item in report.items}
    assert by_name["pack.zip"].status == "failed"
    assert "mesma saída" in (by_name["pack.zip"].detail or "")
    assert by_name["Edicao 01.pdf"].status in {"processed", "failed"}
    assert not (base / "Edicao 01.cbz").exists()


def test_batch_ignores_orphan_extraction_temporaries(tmp_path: Path) -> None:
    (tmp_path / ".banca-abc123.tmp").write_bytes(b"PK\x03\x04")
    (tmp_path / "issue.pdf").write_bytes(b"%PDF-1.4")

    assert [item.source.name for item in plan_batch(tmp_path, tmp_path / "output")] == ["issue.pdf"]


def _touch(path: Path) -> Path:
    path.write_bytes(b"x")
    return path


def test_remove_published_originals_trashes_only_processed_items(tmp_path: Path) -> None:
    trash = tmp_path / "Trash"
    out = tmp_path / "out"
    items = (
        BatchItem(_touch(tmp_path / "ok.pdf"), out / "ok.cbr", "convert", "processed", "10 páginas"),
        BatchItem(_touch(tmp_path / "fail.cbr"), out / "fail.cbr", "process-cbr", "failed", "erro"),
        BatchItem(_touch(tmp_path / "old.cbz"), out / "old.cbr", "convert", "skipped", "saída já existe"),
        BatchItem(_touch(tmp_path / "notes.txt"), out / "notes.cbr", "unsupported", "unsupported"),
    )

    result = remove_published_originals(items, trash)

    assert [(item.source.name, item.source_removed) for item in result] == [
        ("ok.pdf", True),
        ("fail.cbr", False),
        ("old.cbz", False),
        ("notes.txt", False),
    ]
    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == ["fail.cbr", "notes.txt", "old.cbz"]
    assert (trash / "files" / "ok.pdf").exists()


def test_remove_published_originals_trashes_container_only_after_all_its_comics(tmp_path: Path) -> None:
    trash = tmp_path / "Trash"
    out = tmp_path / "out"
    done = _touch(tmp_path / "A 01.cbz")
    broken = _touch(tmp_path / "B 01.cbz")
    complete = BatchItem(_touch(tmp_path / "A.zip"), tmp_path, "extract", "extracted", extracted=(done,))
    partial = BatchItem(
        _touch(tmp_path / "B.zip"), tmp_path, "extract", "extracted", extracted=(broken, _touch(tmp_path / "B 02.cbz"))
    )
    items = (
        BatchItem(done, out / "A 01.cbr", "convert", "processed"),
        BatchItem(broken, out / "B 01.cbr", "convert", "failed", "erro"),
        BatchItem(tmp_path / "B 02.cbz", out / "B 02.cbr", "convert", "processed"),
        complete,
        partial,
    )

    result = {item.source.name: item for item in remove_published_originals(items, trash)}

    assert result["A.zip"].source_removed
    assert not result["B.zip"].source_removed
    assert sorted(path.name for path in tmp_path.iterdir() if path.is_file()) == ["B 01.cbz", "B.zip"]


def test_remove_published_originals_handles_nested_containers(tmp_path: Path) -> None:
    trash = tmp_path / "Trash"
    comic = _touch(tmp_path / "issue.cbz")
    inner = _touch(tmp_path / "inner.zip")
    items = (
        BatchItem(comic, tmp_path / "out" / "issue.cbr", "convert", "processed"),
        BatchItem(_touch(tmp_path / "outer.zip"), tmp_path, "extract", "extracted", extracted=(inner,)),
        BatchItem(inner, tmp_path, "extract", "extracted", extracted=(comic,)),
    )

    result = remove_published_originals(items, trash)

    assert all(item.source_removed for item in result)
    assert not [path for path in tmp_path.iterdir() if path.is_file()]


def test_remove_published_originals_keeps_item_when_trash_fails(tmp_path: Path) -> None:
    trash = _touch(tmp_path / "Trash")
    source = _touch(tmp_path / "ok.pdf")

    (result,) = remove_published_originals(
        (BatchItem(source, tmp_path / "out" / "ok.cbr", "convert", "processed", "10 páginas"),), trash
    )

    assert result.status == "processed"
    assert not result.source_removed
    assert "original mantido" in (result.detail or "")
    assert source.exists()


def test_batch_dry_run_never_removes_originals(tmp_path: Path) -> None:
    (tmp_path / "issue.pdf").write_bytes(b"%PDF-1.4")

    report = run_batch(tmp_path, tmp_path / "output", remove_originals=True, trash_dir=tmp_path / "Trash")

    assert report.remove_originals
    assert (tmp_path / "issue.pdf").exists()
    assert not (tmp_path / "Trash").exists()


def test_batch_report_serializes_removal_fields(tmp_path: Path) -> None:
    from banca_revista.batch import BatchReport

    item = BatchItem(tmp_path / "A.zip", tmp_path, "extract", "extracted", extracted=(tmp_path / "A 01.cbz",))
    payload = json.loads(BatchReport(tmp_path, tmp_path / "out", False, 1, (item,), remove_originals=True).to_json())

    assert payload["remove_originals"] is True
    assert payload["items"][0]["extracted"] == [str(tmp_path / "A 01.cbz")]
    assert payload["items"][0]["source_removed"] is False


@pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("rar", "unrar", "tesseract", "magick")),
    reason="ferramentas externas não instaladas",
)
def test_batch_removes_container_and_extracted_comics_after_publishing(tmp_path: Path) -> None:
    base = tmp_path / "source"
    base.mkdir()
    _write_comic_container(base / "Rainha.zip", ["Rainha 01", "Rainha 02"])
    (base / "notes.txt").write_text("não é quadrinho")
    output = tmp_path / "output"
    trash = tmp_path / "Trash"

    report = run_batch(
        base, output, dry_run=False, lookup_isbn=False, workers=2, remove_originals=True, trash_dir=trash
    )

    assert [(item.source.name, item.status, item.source_removed) for item in report.items] == [
        ("notes.txt", "unsupported", False),
        ("Rainha 01.cbz", "processed", True),
        ("Rainha 02.cbz", "processed", True),
        ("Rainha.zip", "extracted", True),
    ]
    assert sorted(path.name for path in base.iterdir()) == ["notes.txt"]
    assert sorted(path.name for path in output.glob("*.cbr")) == ["Rainha 01.cbr", "Rainha 02.cbr"]
    assert sorted(path.name for path in (trash / "files").iterdir()) == ["Rainha 01.cbz", "Rainha 02.cbz", "Rainha.zip"]


def test_cli_dry_run_with_remove_originals_keeps_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from banca_revista import cli

    (tmp_path / "issue.pdf").write_bytes(b"%PDF-1.4")
    output = tmp_path / "output"
    monkeypatch.setattr("sys.argv", ["banca-revista", "batch-to-cbr", str(tmp_path), str(output), "--remove-originals"])

    assert cli.main() == 0

    assert "Lixeira após publicação" in capsys.readouterr().out
    assert (tmp_path / "issue.pdf").exists()
    assert not output.exists()
