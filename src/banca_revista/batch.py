"""Planejamento e execução em lote da biblioteca de quadrinhos."""

from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from banca_revista.archive import ConversionError, natural_key
from banca_revista.pipeline import process_to_library

CONVERT_INPUTS = frozenset({".pdf", ".zip", ".cbz"})
UNSUPPORTED_INPUTS = frozenset({".epub", ".rar"})
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


def plan_batch(base: Path, output_dir: Path) -> tuple[BatchItem, ...]:
    """Planeja primeiro conversões e depois todos os CBRs existentes."""
    source_dir = base.resolve(strict=True)
    if not source_dir.is_dir():
        raise ConversionError(f"a base não é um diretório: {source_dir}")
    destination_dir = output_dir.resolve()
    files = [path for path in source_dir.iterdir() if path.is_file()]
    conversions = sorted((path for path in files if path.suffix.casefold() in CONVERT_INPUTS), key=_path_key)
    comics = sorted((path for path in files if path.suffix.casefold() == ".cbr"), key=_path_key)
    unsupported = sorted((path for path in files if path.suffix.casefold() in UNSUPPORTED_INPUTS), key=_path_key)
    seen: dict[str, Path] = {}
    items: list[BatchItem] = []
    for source, phase, status in (
        *((path, "convert", "planned") for path in conversions),
        *((path, "process-cbr", "planned") for path in comics),
        *((path, "unsupported", "unsupported") for path in unsupported),
    ):
        output = destination_dir / f"{source.stem}.cbr"
        collision_key = output.name.casefold()
        if status == "planned" and collision_key in seen:
            raise ConversionError(f"duas origens produziriam a mesma saída: {seen[collision_key].name} e {source.name}")
        if status == "planned":
            seen[collision_key] = source
        detail = f"extensão {source.suffix} não é quadrinho suportado" if status == "unsupported" else None
        items.append(BatchItem(source=source, output=output, phase=phase, status=status, detail=detail))
    return tuple(items)


def run_batch(
    base: Path,
    output_dir: Path,
    *,
    dry_run: bool = True,
    lookup_isbn: bool = True,
    workers: int = DEFAULT_WORKERS,
) -> BatchReport:
    """Executa cada fase em processos isolados e sem sobrescrever saídas."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ConversionError(f"workers deve estar entre 1 e {MAX_WORKERS}")
    source_dir = base.resolve(strict=True)
    destination_dir = output_dir.resolve()
    planned = plan_batch(source_dir, destination_dir)
    if dry_run:
        return BatchReport(source_dir, destination_dir, True, workers, planned)

    destination_dir.mkdir(parents=True, exist_ok=True)
    completed: list[BatchItem | None] = [None] * len(planned)
    pending_by_phase: dict[str, list[tuple[int, BatchItem]]] = {"convert": [], "process-cbr": []}
    for index, item in enumerate(planned):
        if item.status == "unsupported":
            completed[index] = item
            continue
        pending_by_phase[item.phase].append((index, item))

    with ProcessPoolExecutor(max_workers=workers) as executor:
        for phase in ("convert", "process-cbr"):
            futures = {
                executor.submit(_process_item, item, lookup_isbn=lookup_isbn): index
                for index, item in pending_by_phase[phase]
            }
            for future in as_completed(futures):
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

    return BatchReport(
        source_dir, destination_dir, False, workers, tuple(item for item in completed if item is not None)
    )


def _process_item(item: BatchItem, *, lookup_isbn: bool) -> BatchItem:
    """Processa um item em subprocesso sem depender de estado mutável do pai."""
    if item.output.exists():
        return BatchItem(item.source, item.output, item.phase, "skipped", "saída já existe")
    try:
        result = process_to_library(item.source, item.output, lookup_isbn=lookup_isbn)
    except (ConversionError, OSError) as error:
        return BatchItem(item.source, item.output, item.phase, "failed", str(error))
    detail = f"{result.page_count} páginas; {result.strategy}"
    if result.warnings:
        detail = f"{detail}; avisos: {' | '.join(result.warnings)}"
    return BatchItem(item.source, item.output, item.phase, "processed", detail)


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
