"""Pipeline unificado de normalização, OCR e metadados para a biblioteca final."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from banca_revista.archive import ConversionError
from banca_revista.cbr import convert_to_cbr
from banca_revista.metadata import (
    ComicMetadata,
    best_effort_metadata,
    create_metadata_cbr,
    parse_comic_metadata,
    read_rar_comment,
)
from banca_revista.ocr import OcrError, analyze_cbr

StageCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class ProcessingResult:
    """Resultado final de um item publicado na biblioteca."""

    source: Path
    output: Path
    page_count: int
    first_page: str
    strategy: str
    metadata: ComicMetadata
    warnings: tuple[str, ...] = ()


def process_to_library(
    source: Path,
    output: Path,
    *,
    lookup_isbn: bool = True,
    replace_existing: bool = False,
    stage_callback: StageCallback | None = None,
) -> ProcessingResult:
    """Normaliza para RAR 5, executa OCR e publica uma cópia enriquecida."""
    original = source.resolve(strict=True)
    destination = output.resolve()
    if destination.suffix.casefold() != ".cbr":
        raise ConversionError("o arquivo final deve usar a extensão .cbr")
    if destination.exists() and not replace_existing:
        raise ConversionError(f"o arquivo final já existe: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f".{destination.stem}-", dir=destination.parent) as temporary_name:
        temporary = Path(temporary_name)
        normalized = temporary / original.with_suffix(".cbr").name
        _emit_stage(stage_callback, "🔄 Normalizando para RAR 5", 1)
        conversion = convert_to_cbr(original, normalized)
        existing = _read_metadata(normalized)
        _emit_stage(stage_callback, "🔎 Lendo capa, OCR e ISBN", 2)
        try:
            report = analyze_cbr(normalized, lookup_isbn=lookup_isbn, strict_lookup=False)
        except OcrError as error:
            report = None
            warnings.append(f"OCR ignorado: {error}")
        else:
            warnings.extend(candidate.value for candidate in report.candidates if candidate.field == "catalog_error")
            if not any(candidate.field == "isbn" for candidate in report.candidates):
                warnings.append(f"ISBN não encontrado nas {len(report.pages)} primeiras páginas")
        metadata = best_effort_metadata(report, fallback_title=original.stem, existing=existing)
        enriched = temporary / "enriched.cbr"
        _emit_stage(stage_callback, "📝 Metadados e validação final", 3)
        create_metadata_cbr(normalized, enriched, metadata)
        _emit_stage(stage_callback, "📤 Publicando na biblioteca", 4)
        _publish(enriched, destination, replace_existing=replace_existing)

    return ProcessingResult(
        source=original,
        output=destination,
        page_count=conversion.page_count,
        first_page=conversion.first_page,
        strategy=conversion.strategy,
        metadata=metadata,
        warnings=tuple(warnings),
    )


def _emit_stage(callback: StageCallback | None, label: str, position: int) -> None:
    if callback is not None:
        callback(label, position, 4)


def _read_metadata(path: Path) -> ComicMetadata | None:
    try:
        return parse_comic_metadata(read_rar_comment(path))
    except (ConversionError, UnicodeDecodeError):
        return None


def _publish(temporary: Path, destination: Path, *, replace_existing: bool) -> None:
    if replace_existing:
        temporary.replace(destination)
        return
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ConversionError(f"o arquivo final já existe: {destination}") from error
