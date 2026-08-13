"""Apresentação colorida e interativa do processamento em lote."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from banca_revista.batch import BatchItem, BatchProgressEvent, BatchReport

_PHASES = {
    "convert": ("🔄 Conversão", "cyan"),
    "process-cbr": ("📚 Normalização + metadados", "magenta"),
    "unsupported": ("🚫 Não suportados", "yellow"),
}


class BatchProgressDisplay:
    """Traduz eventos do lote em barras Rich sem acessar os subprocessos."""

    def __init__(self, console: Console, *, base: Path, output_dir: Path, workers: int) -> None:
        self.console = console
        self.base = base
        self.output_dir = output_dir
        self.workers = workers
        self.progress = Progress(
            SpinnerColumn(style="bold cyan"),
            TextColumn("{task.description}", justify="left"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TextColumn("[dim]{task.completed:.0f}/{task.total:.0f}[/dim]"),
            TimeElapsedColumn(),
            console=console,
            expand=True,
        )
        self.overall_task: TaskID | None = None
        self.worker_status_task: TaskID | None = None
        self.phase_tasks: dict[str, TaskID] = {}
        self.worker_tasks: dict[int, TaskID] = {}
        self.worker_items: dict[int, Path] = {}
        self.total = 0
        self.completed = 0
        self.statuses: Counter[str] = Counter()

    def __enter__(self) -> BatchProgressDisplay:
        self.console.print(
            Panel.fit(
                "[bold cyan]📚 Banca Revista[/bold cyan]\n[dim]Normalização, OCR e metadados em paralelo[/dim]",
                border_style="cyan",
            )
        )
        self.progress.start()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.progress.stop()

    def __call__(self, event: BatchProgressEvent) -> None:
        if event.kind == "planned":
            self._start(event.items)
            return
        if event.kind == "started":
            self._worker_started(event)
            return
        if event.kind == "stage":
            self._worker_stage(event)
            return
        if event.item is None or self.overall_task is None:
            return
        item = event.item
        self.completed += 1
        self.statuses[item.status] += 1
        self.progress.advance(self.overall_task)
        phase_task = self.phase_tasks.get(item.phase)
        if phase_task is not None:
            self.progress.advance(phase_task)
        icon, style = _status_display(item.status)
        self.progress.update(
            self.overall_task,
            description=(
                f"[bold blue]🚀 Total[/bold blue] [dim]•[/dim] [{style}]{icon} {escape(item.source.name)}[/{style}]"
            ),
        )
        worker_id = event.worker_id or self._worker_for(item.source)
        if worker_id is not None:
            task_id = self.worker_tasks.pop(worker_id, None)
            self.worker_items.pop(worker_id, None)
            if task_id is not None:
                self.progress.remove_task(task_id)
        self._update_worker_status()

    def _start(self, items: tuple[BatchItem, ...]) -> None:
        phase_counts = Counter(item.phase for item in items)
        self.total = len(items)
        self.progress.console.print(_configuration_table(self.base, self.output_dir, self.workers, phase_counts))
        self.overall_task = self.progress.add_task("[bold blue]🚀 Total[/bold blue]", total=len(items))
        self.worker_status_task = self.progress.add_task("", total=len(items))
        self._update_worker_status()
        for phase, count in phase_counts.items():
            label, style = _PHASES[phase]
            self.phase_tasks[phase] = self.progress.add_task(f"[{style}]{label}[/{style}]", total=count)

    def _worker_started(self, event: BatchProgressEvent) -> None:
        if event.worker_id is None or event.item is None:
            return
        self.worker_items[event.worker_id] = event.item.source
        self.worker_tasks[event.worker_id] = self.progress.add_task(
            self._worker_description(event.worker_id, "⏳ Iniciando", event.item.source.name),
            total=event.stage_total or 4,
        )
        self._update_worker_status()

    def _worker_stage(self, event: BatchProgressEvent) -> None:
        if event.worker_id is None or event.item is None or event.stage is None:
            return
        task_id = self.worker_tasks.get(event.worker_id)
        if task_id is None:
            self._worker_started(event)
            task_id = self.worker_tasks[event.worker_id]
        self.progress.update(
            task_id,
            description=self._worker_description(event.worker_id, event.stage, event.item.source.name),
            completed=max(event.stage_position - 1, 0),
            total=event.stage_total or 4,
        )

    def _update_worker_status(self) -> None:
        if self.worker_status_task is None:
            return
        active = len(self.worker_tasks)
        queued = max(self.total - self.completed - active, 0)
        self.progress.update(
            self.worker_status_task,
            description=(
                f"[bold cyan]⚙️ Workers ativos: {active}/{self.workers}[/bold cyan] "
                f"[dim]•[/dim] [yellow]⏳ Na fila: {queued}[/yellow]"
            ),
            completed=self.completed,
        )

    def _worker_for(self, source: Path) -> int | None:
        return next(
            (worker_id for worker_id, active_source in self.worker_items.items() if active_source == source), None
        )

    @staticmethod
    def _worker_description(worker_id: int, stage: str, filename: str) -> str:
        return f"[cyan]⚙️ {worker_id}[/cyan] [bold]{stage}[/bold] [dim]•[/dim] {escape(filename)}"


def render_plan(console: Console, report: BatchReport) -> None:
    """Mostra uma simulação compacta antes de qualquer escrita."""
    phase_counts = Counter(item.phase for item in report.items)
    console.print(Panel("[bold yellow]🧭 Simulação: nenhum arquivo foi alterado[/bold yellow]", border_style="yellow"))
    console.print(_configuration_table(report.base, report.output_dir, report.workers, phase_counts))
    console.print("[dim]Use [bold]--execute[/bold] para iniciar o processamento.[/dim]")


def render_summary(console: Console, report: BatchReport, *, report_path: Path | None = None) -> None:
    """Exibe o balanço final com os indicadores relevantes."""
    statuses = Counter(item.status for item in report.items)
    warnings = sum("avisos:" in (item.detail or "") for item in report.items)
    with_isbn = sum(item.metadata is not None and item.metadata.isbn is not None for item in report.items)
    status_table = Table.grid(padding=(0, 2))
    status_table.add_column(justify="right")
    status_table.add_column()
    status_table.add_row("[bold green]✅ Processados[/bold green]", str(statuses["processed"]))
    status_table.add_row("[bold yellow]⏭️  Ignorados[/bold yellow]", str(statuses["skipped"]))
    status_table.add_row("[bold red]❌ Falhas[/bold red]", str(statuses["failed"]))
    status_table.add_row("[yellow]⚠️  Com avisos[/yellow]", str(warnings))
    status_table.add_row("[cyan]🔎 Com ISBN[/cyan]", str(with_isbn))
    footer = Text()
    if report_path is not None:
        footer.append("\n🧾 Relatório: ", style="dim")
        footer.append(str(report_path), style="bold cyan")
    border = "red" if statuses["failed"] else "green"
    title = "❌ Processamento concluído com falhas" if statuses["failed"] else "🎉 Processamento concluído"
    console.print(Panel(Group(status_table, footer), title=title, border_style=border))
    failures = [item for item in report.items if item.status == "failed"]
    if failures:
        failure_table = Table(title="❌ Falhas que exigem atenção", border_style="red", expand=True)
        failure_table.add_column("Arquivo", style="bold")
        failure_table.add_column("Motivo", style="red")
        for item in failures:
            failure_table.add_row(item.source.name, item.detail or "falha sem detalhes")
        console.print(failure_table)


def _configuration_table(base: Path, output_dir: Path, workers: int, phase_counts: Counter[str]) -> Table:
    table = Table(title="📋 Plano do lote", border_style="blue", show_header=False, pad_edge=False)
    table.add_column(style="bold blue")
    table.add_column(overflow="fold")
    table.add_row("📥 Origem", Text(str(base)))
    table.add_row("📤 Destino", Text(str(output_dir)))
    table.add_row("⚙️  Processos", str(workers))
    table.add_row("📦 Arquivos", str(sum(phase_counts.values())))
    table.add_row("🔄 Conversões", str(phase_counts["convert"]))
    table.add_row("📚 CBRs", str(phase_counts["process-cbr"]))
    if phase_counts["unsupported"]:
        table.add_row("🚫 Não suportados", str(phase_counts["unsupported"]))
    return table


def _status_display(status: str) -> tuple[str, str]:
    return {
        "processed": ("✅", "green"),
        "skipped": ("⏭️", "yellow"),
        "failed": ("❌", "red"),
        "unsupported": ("🚫", "yellow"),
    }.get(status, ("•", "white"))
