from __future__ import annotations

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
        display(BatchProgressEvent("completed", 2, 1, items, _processed(items[0])))
        display(BatchProgressEvent("completed", 2, 2, items, _processed(items[1])))

    output = stream.getvalue()
    assert "📦 Arquivos" in output
    assert "2" in output
    assert "🔄 Conversão" in output
    assert "📚 Normalização + metadados" in output
    assert "100%" in output
    assert "volume 2.cbr" in output
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
