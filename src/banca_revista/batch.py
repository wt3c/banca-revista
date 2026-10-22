"""Planejamento e execução em lote da biblioteca de quadrinhos."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass, replace
from multiprocessing import get_context
from pathlib import Path, PurePosixPath
from queue import Empty
from typing import Literal, Protocol

from banca_revista.archive import ConversionError, natural_key
from banca_revista.cbr import detect_cbr_source
from banca_revista.container import ContainerInspection, extract_container, inspect_container
from banca_revista.metadata import ComicMetadata
from banca_revista.pipeline import process_to_library
from banca_revista.trash import move_to_trash

DEFAULT_WORKERS = 10
KEPT_ORIGINAL_MARKER = "original mantido: "
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
    source_removed: bool = False
    extracted: tuple[Path, ...] = ()


@dataclass(frozen=True)
class BatchReport:
    """Relatório completo e serializável de uma execução."""

    base: Path
    output_dir: Path
    dry_run: bool
    workers: int
    items: tuple[BatchItem, ...]
    remove_originals: bool = False

    def to_json(self) -> str:
        payload = asdict(self)
        payload["base"] = os.fspath(self.base)
        payload["output_dir"] = os.fspath(self.output_dir)
        for item in payload["items"]:
            item["source"] = os.fspath(item["source"])
            item["output"] = os.fspath(item["output"])
            item["extracted"] = [os.fspath(path) for path in item["extracted"]]
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
    # ".banca-*" são temporários de extração interrompida, nunca quadrinhos do acervo.
    files = [path for path in source_dir.iterdir() if path.is_file() and not path.name.startswith(".banca-")]
    seen: dict[str, Path] = {}
    items: list[BatchItem] = []
    for source in sorted(files, key=_path_key):
        output = destination_dir / f"{source.stem}.cbr"
        try:
            input_format = detect_cbr_source(source)
        except (ConversionError, OSError) as error:
            items.append(BatchItem(source, output, "unsupported", "unsupported", str(error)))
            continue
        if input_format != "pdf" and (container := _inspect_container_or_none(source)) is not None:
            names = "; ".join(PurePosixPath(member.replace("\\", "/")).name for member in container.members)
            detail = f"contém {len(container.members)} quadrinhos: {names}"
            items.append(BatchItem(source, source.parent, "extract", "planned", detail))
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
    remove_originals: bool = False,
    trash_dir: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BatchReport:
    """Executa cada fase em processos isolados e sem sobrescrever saídas.

    Com ``remove_originals``, só depois de todas as fases os originais publicados vão para a Lixeira.
    """
    if not 1 <= workers <= MAX_WORKERS:
        raise ConversionError(f"workers deve estar entre 1 e {MAX_WORKERS}")
    source_dir = base.resolve(strict=True)
    destination_dir = output_dir.resolve()
    planned = plan_batch(source_dir, destination_dir)
    if not dry_run:
        planned = _extract_containers(planned, source_dir, destination_dir)
    if progress_callback is not None:
        progress_callback(BatchProgressEvent("planned", len(planned), 0, planned))
    if dry_run:
        return BatchReport(source_dir, destination_dir, True, workers, planned, remove_originals)

    destination_dir.mkdir(parents=True, exist_ok=True)
    completed: list[BatchItem | None] = [None] * len(planned)
    pending: list[tuple[int, BatchItem]] = []
    for index, item in enumerate(planned):
        if item.status != "planned":
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

    items = tuple(item for item in completed if item is not None)
    if remove_originals:
        items = remove_published_originals(items, trash_dir)
    return BatchReport(source_dir, destination_dir, False, workers, items, remove_originals)


def remove_published_originals(items: tuple[BatchItem, ...], trash_dir: Path | None = None) -> tuple[BatchItem, ...]:
    """Envia à Lixeira só o que foi publicado nesta execução; o resto fica na origem para revisão.

    Um contêiner sai apenas quando todos os quadrinhos extraídos dele já saíram, inclusive contêineres aninhados.
    """
    results = list(items)
    removed: set[Path] = set()

    def trash(index: int) -> None:
        item = results[index]
        try:
            move_to_trash(item.source, trash_dir)
        except OSError as error:
            detail = f"{item.detail}; " if item.detail else ""
            results[index] = replace(item, detail=f"{detail}{KEPT_ORIGINAL_MARKER}{error}")
            return
        removed.add(item.source)
        results[index] = replace(item, source_removed=True)

    for index, item in enumerate(results):
        if item.status == "processed":
            trash(index)
    containers = [index for index, item in enumerate(results) if item.status == "extracted"]
    while ready := [index for index in containers if set(results[index].extracted) <= removed]:
        for index in ready:
            containers.remove(index)
            trash(index)
    return tuple(results)


def _inspect_container_or_none(source: Path) -> ContainerInspection | None:
    """Falhas de leitura ficam para a conversão normal, que já as relata por arquivo."""
    try:
        return inspect_container(source)
    except (ConversionError, OSError):
        return None


def _extract_containers(
    planned: tuple[BatchItem, ...],
    source_dir: Path,
    destination_dir: Path,
) -> tuple[BatchItem, ...]:
    """Extrai contêineres, inclusive aninhados, e replaneja o lote com os quadrinhos extraídos."""
    results: dict[Path, BatchItem] = {}
    while pending := [item for item in planned if item.phase == "extract" and item.source not in results]:
        claimed = {
            item.output.name.casefold(): item.source for item in planned if item.phase not in {"extract", "unsupported"}
        }
        for item in pending:
            results[item.source] = _extract_item(item, claimed)
        planned = plan_batch(source_dir, destination_dir)
    return tuple(results.get(item.source, item) for item in planned)


def _extract_item(item: BatchItem, claimed: dict[str, Path]) -> BatchItem:
    """Recusa o contêiner antes de escrever se algum quadrinho colidir com a saída de outra origem."""
    try:
        container = inspect_container(item.source)
        if container is None:
            raise ConversionError("o arquivo deixou de conter quadrinhos após o planejamento")
        targets = [item.output / PurePosixPath(member.replace("\\", "/")).name for member in container.members]
        for target in targets:
            owner = claimed.get(f"{target.stem}.cbr".casefold())
            if owner is not None and owner != target:
                raise ConversionError(f"{target.name} produziria a mesma saída que {owner.name}")
        extracted = extract_container(container, item.output)
    except (ConversionError, OSError) as error:
        return BatchItem(item.source, item.output, item.phase, "failed", str(error))
    claimed.update((f"{target.stem}.cbr".casefold(), target) for target in targets)
    reused = sum(comic.reused for comic in extracted)
    detail = f"{len(extracted)} quadrinhos extraídos para {item.output}"
    if reused:
        detail = f"{detail} ({reused} já existiam com o mesmo conteúdo)"
    return BatchItem(
        item.source, item.output, item.phase, "extracted", detail, extracted=tuple(comic.path for comic in extracted)
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
