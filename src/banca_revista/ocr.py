"""Extração local e auditável de metadados visíveis em quadrinhos."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from banca_revista.archive import ArchiveInspection, ConversionError, inspect_rar
from banca_revista.catalog import CatalogError, lookup_ndl_isbn

_VOLUME_PATTERN = re.compile(r"\b(?:volume|vol\.?)[\s_-]*(\d+(?:[.,]\d+)?)\b", re.IGNORECASE)
_ISBN_LABEL_PATTERN = re.compile(r"ISBN\s*([0-9Xx][0-9Xx\s-]{8,20})", re.IGNORECASE)
_ISBN_13_PATTERN = re.compile(r"(?<!\d)(97[89](?:[\s-]*\d){10})(?!\d)")
_PERSON_LINE_PATTERN = re.compile(r"^[^\W\d_]+(?:[ .'-]+[^\W\d_]+){1,3}$", re.UNICODE)
_AUTHOR_EXCLUSIONS = frozenset({"isbn", "manga", "volume", "planet", "panini", "comics"})


class OcrError(ConversionError):
    """Erro esperado ao extrair texto ou inferir metadados."""


@dataclass(frozen=True)
class MetadataCandidate:
    """Valor inferido acompanhado de proveniência e confiança."""

    field: str
    value: str
    confidence: float
    evidence: str
    page: str | None = None


@dataclass(frozen=True)
class PageOcr:
    """Texto reconhecido em uma página e em suas regiões relevantes."""

    page: str
    full_text: str
    author_region_texts: tuple[str, ...] = ()
    identifier_region_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class OcrReport:
    """Relatório serializável da análise de um CBR."""

    source: Path
    pages: tuple[PageOcr, ...]
    candidates: tuple[MetadataCandidate, ...]

    def to_json(self) -> str:
        payload = asdict(self)
        payload["source"] = os.fspath(self.source)
        return json.dumps(payload, ensure_ascii=False, indent=2)


def analyze_cbr(
    source: Path,
    *,
    page_count: int = 2,
    unrar: str = "unrar",
    tesseract: str = "tesseract",
    magick: str = "magick",
    lookup_isbn: bool = False,
    strict_lookup: bool = True,
) -> OcrReport:
    """Analisa as primeiras páginas sem modificar o CBR."""
    if page_count < 1:
        raise OcrError("a quantidade de páginas para OCR deve ser positiva")
    inspection = inspect_rar(source, unrar=unrar)
    _require_executable(tesseract, "Tesseract")
    _require_executable(magick, "ImageMagick")

    selected_pages = inspection.pages[:page_count]
    recognized: list[PageOcr] = []
    with tempfile.TemporaryDirectory(prefix="banca-revista-ocr-") as temporary_name:
        temporary = Path(temporary_name)
        for index, page in enumerate(selected_pages):
            image = temporary / f"page-{index}{Path(page.output_name).suffix.lower()}"
            image.write_bytes(_extract_member(inspection, page.source_name, unrar=unrar))
            full_text = _run_tesseract(image, tesseract=tesseract, page_segmentation=11)
            author_texts: tuple[str, ...] = ()
            identifier_texts: tuple[str, ...] = ()
            if index == 0:
                author_texts = _read_author_regions(image, temporary, tesseract=tesseract, magick=magick)
            else:
                identifier_texts = _read_identifier_region(
                    image,
                    temporary,
                    index=index,
                    tesseract=tesseract,
                    magick=magick,
                )
            recognized.append(
                PageOcr(
                    page=page.source_name,
                    full_text=full_text,
                    author_region_texts=author_texts,
                    identifier_region_texts=identifier_texts,
                )
            )

    candidates = list(infer_candidates(source.name, recognized))
    isbn = next((candidate.value for candidate in candidates if candidate.field == "isbn"), None)
    if lookup_isbn and isbn is not None:
        try:
            catalog = lookup_ndl_isbn(isbn)
        except CatalogError as error:
            if strict_lookup:
                raise OcrError(str(error)) from error
            candidates.append(MetadataCandidate("catalog_error", str(error), 0, "consulta por ISBN"))
            catalog = None
        if catalog is not None:
            catalog_fields = (
                ("catalog_title", catalog.title),
                ("author", catalog.author),
                ("publisher", catalog.publisher),
                ("catalog_volume", catalog.volume),
                ("publication_date", catalog.publication_date),
                ("language", catalog.language),
            )
            candidates.extend(
                MetadataCandidate(field, value, 0.99, "catálogo NDL consultado pelo ISBN")
                for field, value in catalog_fields
                if value is not None
            )
    return OcrReport(source=inspection.source, pages=tuple(recognized), candidates=tuple(candidates))


def infer_candidates(filename: str, pages: list[PageOcr]) -> tuple[MetadataCandidate, ...]:
    """Infere somente campos rastreáveis ao nome ou ao texto reconhecido."""
    candidates: list[MetadataCandidate] = []
    stem = Path(filename).stem
    volume_match = _VOLUME_PATTERN.search(stem)
    if volume_match:
        volume = volume_match.group(1).replace(",", ".")
        title = stem[: volume_match.start()].rstrip(" -_[")
        if title:
            candidates.append(MetadataCandidate("title", title, 0.98, "nome do arquivo"))
        candidates.append(MetadataCandidate("volume", volume, 0.99, "nome do arquivo"))

    all_text = "\n".join(_page_text(page) for page in pages)
    isbn = find_isbn(all_text)
    if isbn is not None:
        evidence_page = next((page.page for page in pages if isbn[-6:] in _digits(_page_text(page))), None)
        candidates.append(MetadataCandidate("isbn", isbn, 0.99, "ISBN válido reconhecido por OCR", evidence_page))

    if pages:
        for author in author_candidates(pages[0].author_region_texts):
            candidates.append(
                MetadataCandidate(
                    "author_candidate",
                    author,
                    0.55,
                    "texto semelhante a nome na região superior da capa",
                    pages[0].page,
                )
            )
    return tuple(candidates)


def find_isbn(text: str) -> str | None:
    """Localiza e valida ISBN-13 ou ISBN-10, preferindo ISBN-13."""
    normalized_candidates: list[str] = []
    for pattern in (_ISBN_13_PATTERN, _ISBN_LABEL_PATTERN):
        for match in pattern.finditer(text):
            normalized = _digits_and_x(match.group(1))
            if len(normalized) in {10, 13} and normalized not in normalized_candidates:
                normalized_candidates.append(normalized)
    for length, validator in ((13, _valid_isbn13), (10, _valid_isbn10)):
        for candidate in normalized_candidates:
            if len(candidate) == length and validator(candidate):
                return candidate
    return None


def author_candidates(texts: tuple[str, ...]) -> tuple[str, ...]:
    """Retém nomes plausíveis, sem promovê-los a autor confirmado."""
    candidates: list[str] = []
    for text in texts:
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            words = {word.casefold().strip(".,:;-") for word in line.split()}
            if not (5 <= len(line) <= 60) or words & _AUTHOR_EXCLUSIONS:
                continue
            if _PERSON_LINE_PATTERN.fullmatch(line) and line.casefold() not in {item.casefold() for item in candidates}:
                candidates.append(line)
    return tuple(candidates[:5])


def _read_author_regions(image: Path, temporary: Path, *, tesseract: str, magick: str) -> tuple[str, ...]:
    texts: list[str] = []
    for threshold in (60, 65, 70, 75):
        processed = temporary / f"author-{threshold}.png"
        _run_command(
            [
                magick,
                os.fspath(image),
                "-auto-orient",
                "-resize",
                "3500x3500>",
                "-gravity",
                "NorthEast",
                "-crop",
                "55%x8%+0+15",
                "+repage",
                "-colorspace",
                "Gray",
                "-threshold",
                f"{threshold}%",
                os.fspath(processed),
            ],
            tool="ImageMagick",
        )
        text = _run_tesseract(processed, tesseract=tesseract, page_segmentation=7, languages="eng")
        if text and text not in texts:
            texts.append(text)
    return tuple(texts)


def _read_identifier_region(
    image: Path,
    temporary: Path,
    *,
    index: int,
    tesseract: str,
    magick: str,
) -> tuple[str, ...]:
    processed = temporary / f"identifiers-{index}.png"
    _run_command(
        [
            magick,
            os.fspath(image),
            "-auto-orient",
            "-resize",
            "3500x3500>",
            "-colorspace",
            "Gray",
            "-threshold",
            "60%",
            os.fspath(processed),
        ],
        tool="ImageMagick",
    )
    text = _run_tesseract(processed, tesseract=tesseract, page_segmentation=11, languages="eng")
    return (text,) if text else ()


def _extract_member(inspection: ArchiveInspection, name: str, *, unrar: str) -> bytes:
    result = _run_command(
        [unrar, "p", "-inul", "-p-", "--", os.fspath(inspection.source), name],
        tool="unrar",
    )
    return result.stdout


def _run_tesseract(
    image: Path,
    *,
    tesseract: str,
    page_segmentation: int,
    languages: str = "eng+por",
) -> str:
    result = _run_command(
        [tesseract, os.fspath(image), "stdout", "-l", languages, "--psm", str(page_segmentation)],
        tool="Tesseract",
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def _run_command(command: list[str], *, tool: str) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except FileNotFoundError as error:
        raise OcrError(f"{tool} não foi encontrado") from error
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or f"código {result.returncode}"
        raise OcrError(f"falha ao executar {tool}: {detail}")
    return result


def _require_executable(executable: str, label: str) -> None:
    if shutil.which(executable) is None:
        raise OcrError(f"{label} não foi encontrado no PATH")


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _page_text(page: PageOcr) -> str:
    return "\n".join((page.full_text, *page.author_region_texts, *page.identifier_region_texts))


def _digits_and_x(value: str) -> str:
    return "".join(character.upper() for character in value if character.isdigit() or character.upper() == "X")


def _valid_isbn13(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    total = sum(int(character) * (1 if index % 2 == 0 else 3) for index, character in enumerate(value[:12]))
    return (10 - total % 10) % 10 == int(value[-1])


def _valid_isbn10(value: str) -> bool:
    if len(value) != 10 or not value[:9].isdigit() or not (value[-1].isdigit() or value[-1] == "X"):
        return False
    digits = [int(character) for character in value[:9]] + [10 if value[-1] == "X" else int(value[-1])]
    return sum(weight * digit for weight, digit in zip(range(10, 0, -1), digits, strict=True)) % 11 == 0
