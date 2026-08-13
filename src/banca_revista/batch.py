"""Planejamento e execução em lote da biblioteca de quadrinhos."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from typing import Literal, Protocol

from banca_revista.archive import ConversionError, natural_key
from banca_revista.cbr import detect_cbr_source
from banca_revista.metadata import ComicMetadata
from banca_revista.pipeline import process_to_library

DEFAULT_WORKERS = 10
MAX_WORKERS = 64


@dataclass(frozen=True)
class BatchItem:
    """Resultado individual, inclusive falhas e arquivos já existentes."""

    source: Path
    output: Path
    phase: str
    status: str
    detail: str | None = None
    metadata: ComicMetadata | None = None


@dataclass(frozen=True)
class BatchReport:
    """Relatório completo e serializável de uma execução."""

    base: Path
    output_dir: Path
    dry_run: bool
    workers: int
    items: tuple[BatchItem, ...]

    def to_json(self) -> str:
        payload = asdict(self)
        payload["base"] = os.fspath(self.base)
        payload["output_dir"] = os.fspath(self.output_dir)
        for item in payload["items"]:
            item["source"] = os.fspath(item["source"])
            item["output"] = os.fspath(item["output"])
        return json.dumps(payload, ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class BatchProgressEvent:
    """Evento emitido pelo lote ou por um worker para atualizar a interface."""

    kind: Literal["planned", "started", "stage", "completed"]
    total: int = 0
    completed: int = 0
    items: tuple[BatchItem, ...] = ()
    item: BatchItem | None = None
    worker_id: int | None = None
    stage: str | None = None
    stage_position: int = 0
    stage_total: int = 0


ProgressCallback = Callable[[BatchProgressEvent], None]


class ProgressQueue(Protocol):
    def put(self, event: BatchProgressEvent) -> None: ...

    def get_nowait(self) -> BatchProgressEvent: ...


_WORKER_PROGRESS_QUEUE: ProgressQueue | None = None


def plan_batch(base: Path, output_dir: Path) -> tuple[BatchItem, ...]:
    """Planeja arquivos suportados pelo conteúdo, sem confiar na extensão."""
    source_dir = base.resolve(strict=True)
    if not source_dir.is_dir():
        raise ConversionError(f"a base não é um diretório: {source_dir}")
    destination_dir = output_dir.resolve()
    files = [path for path in source_dir.iterdir() if path.is_file()]
    seen: dict[str, Path] = {}
    items: list[BatchItem] = []
    for source in sorted(files, key=_path_key):
        output = destination_dir / f"{source.stem}.cbr"
        try:
            input_format = detect_cbr_source(source)
        except (ConversionError, OSError) as error:
            items.append(BatchItem(source, output, "unsupported", "unsupported", str(error)))
            continue
        phase = "process-cbr" if input_format == "rar" and source.suffix.casefold() == ".cbr" else "convert"
        collision_key = output.name.casefold()
        if collision_key in seen:
            raise ConversionError(f"duas origens produziriam a mesma saída: {seen[collision_key].name} e {source.name}")
        seen[collision_key] = source
        items.append(BatchItem(source=source, output=output, phase=phase, status="planned"))
    return tuple(items)


def run_batch(
    base: Path,
    output_dir: Path,
    *,
    dry_run: bool = True,
    lookup_isbn: bool = True,
    workers: int = DEFAULT_WORKERS,
    replace_existing: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> BatchReport:
    """Executa cada fase em processos isolados e sem sobrescrever saídas."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ConversionError(f"workers deve estar entre 1 e {MAX_WORKERS}")
    source_dir = base.resolve(strict=True)
    destination_dir = output_dir.resolve()
    planned = plan_batch(source_dir, destination_dir)
    if progress_callback is not None:
        progress_callback(BatchProgressEvent("planned", len(planned), 0, planned))
    if dry_run:
        return BatchReport(source_dir, destination_dir, True, workers, planned)

    destination_dir.mkdir(parents=True, exist_ok=True)
    completed: list[BatchItem | None] = [None] * len(planned)
    pending: list[tuple[int, BatchItem]] = []
    for index, item in enumerate(planned):
        if item.status == "unsupported":
            completed[index] = item
            if progress_callback is not None:
                progress_callback(
                    BatchProgressEvent(
                        "completed",
                        len(planned),
                        sum(result is not None for result in completed),
                        planned,
                        item,
                    )
                )
            continue
        pending.append((index, item))

    event_queue = get_context().Queue() if progress_callback is not None else None
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize_worker_progress,
            initargs=(event_queue,),
        ) as executor:
            futures = {
                executor.submit(
                    _process_item,
                    item,
                    lookup_isbn=lookup_isbn,
                    replace_existing=replace_existing,
                ): index
                for index, item in pending
            }
            remaining = set(futures)
            while remaining:
                done, remaining = wait(remaining, timeout=0.1, return_when=FIRST_COMPLETED)
                _drain_progress_events(event_queue, progress_callback)
                for future in done:
                    index = futures[future]
                    item = planned[index]
                    try:
                        completed[index] = future.result()
                    except Exception as error:  # pragma: no cover - protege contra falha abrupta do subprocesso
                        completed[index] = BatchItem(
                            item.source,
                            item.output,
                            item.phase,
                            "failed",
                            f"falha inesperada no processo: {type(error).__name__}: {error}",
                        )
                        if progress_callback is not None:
                            progress_callback(BatchProgressEvent("completed", item=completed[index]))
                    else:
                        _drain_progress_events(event_queue, progress_callback)
            _drain_progress_events(event_queue, progress_callback)
        _drain_progress_events(event_queue, progress_callback)
    finally:
        if event_queue is not None:
            event_queue.close()
            event_queue.join_thread()

    return BatchReport(
        source_dir, destination_dir, False, workers, tuple(item for item in completed if item is not None)
    )


def _process_item(
    item: BatchItem,
    *,
    lookup_isbn: bool,
    replace_existing: bool,
) -> BatchItem:
    """Processa um item em subprocesso sem depender de estado mutável do pai."""
    worker_id = os.getpid()
    _put_progress_event(_WORKER_PROGRESS_QUEUE, BatchProgressEvent("started", item=item, worker_id=worker_id))
    if item.output.exists() and not replace_existing:
        result = BatchItem(item.source, item.output, item.phase, "skipped", "saída já existe")
        _put_progress_event(_WORKER_PROGRESS_QUEUE, BatchProgressEvent("completed", item=result, worker_id=worker_id))
        return result

    def emit_stage(label: str, position: int, total: int) -> None:
        _put_progress_event(
            _WORKER_PROGRESS_QUEUE,
            BatchProgressEvent(
                "stage",
                item=item,
                worker_id=worker_id,
                stage=label,
                stage_position=position,
                stage_total=total,
            ),
        )

    try:
        result = process_to_library(
            item.source,
            item.output,
            lookup_isbn=lookup_isbn,
            replace_existing=replace_existing,
            stage_callback=emit_stage,
        )
    except (ConversionError, OSError) as error:
        result = BatchItem(item.source, item.output, item.phase, "failed", str(error))
        _put_progress_event(_WORKER_PROGRESS_QUEUE, BatchProgressEvent("completed", item=result, worker_id=worker_id))
        return result
    detail = f"{result.page_count} páginas; capa: {result.first_page}; {result.strategy}"
    if result.warnings:
        detail = f"{detail}; avisos: {' | '.join(result.warnings)}"
    completed = BatchItem(item.source, item.output, item.phase, "processed", detail, result.metadata)
    _put_progress_event(_WORKER_PROGRESS_QUEUE, BatchProgressEvent("completed", item=completed, worker_id=worker_id))
    return completed


def _initialize_worker_progress(queue: ProgressQueue | None) -> None:
    global _WORKER_PROGRESS_QUEUE
    _WORKER_PROGRESS_QUEUE = queue


def _put_progress_event(queue: ProgressQueue | None, event: BatchProgressEvent) -> None:
    if queue is not None:
        queue.put(event)


def _drain_progress_events(queue: ProgressQueue | None, callback: ProgressCallback | None) -> None:
    if queue is None:
        return
    while True:
        try:
            event = queue.get_nowait()
        except Empty:
            return
        if callback is not None:
            callback(event)


def save_report(report: BatchReport, path: Path) -> Path:
    """Publica o relatório atomicamente sem substituir um relatório anterior."""
    destination = path.resolve()
    if destination.exists():
        raise ConversionError(f"o relatório já existe: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(report.to_json())
            stream.write("\n")
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ConversionError(f"o relatório já existe: {destination}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def next_report_path(output_dir: Path) -> Path:
    """Escolhe um nome livre sem sobrescrever relatórios de lotes anteriores."""
    destination_dir = output_dir.resolve()
    first = destination_dir / "conversion-report.json"
    if not first.exists():
        return first
    sequence = 2
    while (candidate := destination_dir / f"conversion-report-{sequence}.json").exists():
        sequence += 1
    return candidate


def _path_key(path: Path):
    return natural_key(path.name)
