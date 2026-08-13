"""Pipeline unificado de normalização, OCR e metadados para a biblioteca final."""

from __future__ import annotations

import os
import tempfile
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


@dataclass(frozen=True)
class ProcessingResult:
    """Resultado final de um item publicado na biblioteca."""

    source: Path
    output: Path
    page_count: int
    strategy: str
    metadata: ComicMetadata
    warnings: tuple[str, ...] = ()


def process_to_library(source: Path, output: Path, *, lookup_isbn: bool = True) -> ProcessingResult:
    """Normaliza para RAR 5, executa OCR e publica uma cópia enriquecida."""
    original = source.resolve(strict=True)
    destination = output.resolve()
    if destination.suffix.casefold() != ".cbr":
        raise ConversionError("o arquivo final deve usar a extensão .cbr")
    if destination.exists():
        raise ConversionError(f"o arquivo final já existe: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix=f".{destination.stem}-", dir=destination.parent) as temporary_name:
        temporary = Path(temporary_name)
        normalized = temporary / original.with_suffix(".cbr").name
        conversion = convert_to_cbr(original, normalized)
        existing = _read_metadata(normalized)
        try:
            report = analyze_cbr(normalized, lookup_isbn=lookup_isbn, strict_lookup=False)
        except OcrError as error:
            report = None
            warnings.append(f"OCR ignorado: {error}")
        else:
            warnings.extend(candidate.value for candidate in report.candidates if candidate.field == "catalog_error")
        metadata = best_effort_metadata(report, fallback_title=original.stem, existing=existing)
        enriched = temporary / "enriched.cbr"
        create_metadata_cbr(normalized, enriched, metadata)
        _publish_without_overwrite(enriched, destination)

    return ProcessingResult(
        source=original,
        output=destination,
        page_count=conversion.page_count,
        strategy=conversion.strategy,
        metadata=metadata,
        warnings=tuple(warnings),
    )


def _read_metadata(path: Path) -> ComicMetadata | None:
    try:
        return parse_comic_metadata(read_rar_comment(path))
    except (ConversionError, UnicodeDecodeError):
        return None


def _publish_without_overwrite(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ConversionError(f"o arquivo final já existe: {destination}") from error
