from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

from rich.console import Console

from banca_revista.batch import BatchItem, BatchProgressEvent, BatchReport
from banca_revista.metadata import ComicMetadata
from banca_revista.presentation import BatchProgressDisplay, render_plan, render_summary


def test_progress_display_shows_counts_phases_percentage_and_current_file(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, color_system="standard", force_terminal=True, width=120)
    items = (
        BatchItem(tmp_path / "volume [1].zip", tmp_path / "volume [1].cbr", "convert", "planned"),
        BatchItem(tmp_path / "volume 2.cbr", tmp_path / "volume 2.cbr", "process-cbr", "planned"),
    )

    with BatchProgressDisplay(console, base=tmp_path, output_dir=tmp_path / "out", workers=2) as display:
        display(BatchProgressEvent("planned", 2, 0, items))
        display(BatchProgressEvent("started", item=items[0], worker_id=101))
        display(
            BatchProgressEvent(
                "stage",
                item=items[0],
                worker_id=101,
                stage="🔎 Lendo capa, OCR e ISBN",
                stage_position=2,
                stage_total=4,
            )
        )
        display(BatchProgressEvent("started", item=items[1], worker_id=202))
        status = next(task for task in display.progress.tasks if task.id == display.worker_status_task)
        first_worker = next(task for task in display.progress.tasks if task.id == display.worker_tasks[101])
        assert "Workers ativos: 2/2" in status.description
        assert "Na fila: 0" in status.description
        assert "Lendo capa, OCR e ISBN" in first_worker.description
        assert "101" in first_worker.description
        display(BatchProgressEvent("completed", 2, 1, items, _processed(items[0])))
        display(BatchProgressEvent("completed", 2, 2, items, _processed(items[1])))
        assert display.worker_tasks == {}
        assert display.completed == 2

    output = stream.getvalue()
    plain_output = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", output)
    assert "📦 Arquivos" in plain_output
    assert "2" in plain_output
    assert "🔄 Conversão" in plain_output
    assert "📚 Normalização + metadados" in plain_output
    assert "100%" in plain_output
    assert "volume 2.cbr" in plain_output
    assert "\x1b[" in output


def test_summary_and_dry_run_are_human_readable(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, color_system=None, force_terminal=False, width=120)
    items = (
        BatchItem(
            tmp_path / "ok.cbr",
            tmp_path / "out" / "ok.cbr",
            "process-cbr",
            "processed",
            "10 páginas",
            ComicMetadata(title="OK", isbn="9784088768120"),
        ),
        BatchItem(tmp_path / "fail.cbr", tmp_path / "out" / "fail.cbr", "process-cbr", "failed", "erro"),
    )
    report = BatchReport(tmp_path, tmp_path / "out", False, 2, items)

    render_summary(console, report, report_path=tmp_path / "report.json")
    render_plan(console, BatchReport(tmp_path, tmp_path / "out", True, 2, items))

    output = stream.getvalue()
    assert "Processamento concluído com falhas" in output
    assert "Com ISBN" in output
    assert "Falhas que exigem atenção" in output
    assert "Simulação: nenhum arquivo foi alterado" in output
    assert "--execute" in output


def _processed(item: BatchItem) -> BatchItem:
    return BatchItem(item.source, item.output, item.phase, "processed", "10 páginas")


def test_plan_and_summary_show_container_extraction(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, color_system=None, force_terminal=False, width=120)
    planned = BatchItem(tmp_path / "pack.zip", tmp_path, "extract", "planned", "contém 2 quadrinhos")
    extracted = BatchItem(tmp_path / "pack.zip", tmp_path, "extract", "extracted", "2 quadrinhos extraídos")

    render_plan(console, BatchReport(tmp_path, tmp_path / "out", True, 2, (planned,)))
    render_summary(console, BatchReport(tmp_path, tmp_path / "out", False, 2, (extracted,)))
    with BatchProgressDisplay(console, base=tmp_path, output_dir=tmp_path / "out", workers=2) as display:
        display(BatchProgressEvent("planned", 1, 0, (extracted,)))
        display(BatchProgressEvent("completed", 1, 1, (extracted,), extracted))

    output = stream.getvalue()
    assert "📂 Contêineres" in output
    assert "📂 Contêineres extraídos" in output
    assert "Processamento concluído" in output


def test_plan_and_summary_show_originals_sent_to_trash(tmp_path: Path) -> None:
    stream = StringIO()
    console = Console(file=stream, color_system=None, force_terminal=False, width=120)
    removed = BatchItem(tmp_path / "ok.pdf", tmp_path / "out" / "ok.cbr", "convert", "processed", source_removed=True)
    kept = BatchItem(
        tmp_path / "ok2.pdf", tmp_path / "out" / "ok2.cbr", "convert", "processed", "original mantido: sem permissão"
    )

    render_plan(console, BatchReport(tmp_path, tmp_path / "out", True, 2, (), remove_originals=True))
    render_summary(console, BatchReport(tmp_path, tmp_path / "out", False, 2, (removed, kept), remove_originals=True))

    output = stream.getvalue()
    assert "🗑️  Originais" in output
    assert "Lixeira após publicação" in output
    assert "🗑️  Originais na Lixeira" in output
    assert "Originais mantidos" in output
    assert "ok2.pdf" in output
    assert "sem permissão" in output
