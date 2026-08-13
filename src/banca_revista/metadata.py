"""Metadados ComicBookInfo para arquivos CBR/RAR."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from banca_revista.archive import ConversionError, detect_archive_format, inspect_rar
from banca_revista.ocr import OcrReport


@dataclass(frozen=True)
class ComicMetadata:
    """Campos suportados pelo projeto e pelo plugin do Calibre."""

    title: str
    authors: tuple[str, ...] = ()
    series: str | None = None
    volume: float | None = None
    isbn: str | None = None
    publisher: str | None = None
    tags: tuple[str, ...] = ()
    comments: str | None = None

    def to_comment(self) -> str:
        book: dict[str, object] = {"title": self.title}
        if self.authors:
            book["credits"] = [{"person": author, "role": "Writer"} for author in self.authors]
        if self.series:
            book["series"] = self.series
        if self.volume is not None:
            book["volume"] = self.volume
        if self.isbn:
            book["isbn"] = self.isbn
        if self.publisher:
            book["publisher"] = self.publisher
        if self.tags:
            book["tags"] = list(self.tags)
        if self.comments:
            book["comments"] = self.comments
        return json.dumps({"ComicBookInfo/1.0": book}, ensure_ascii=False, separators=(",", ":"))


def metadata_from_ocr(
    report: OcrReport,
    *,
    author: str | None = None,
    publisher: str | None = None,
    tags: tuple[str, ...] = (),
) -> ComicMetadata:
    """Promove somente candidatos confiáveis e permite substituir a grafia do autor."""
    values = {candidate.field: candidate.value for candidate in report.candidates if candidate.confidence >= 0.9}
    title = values.get("title")
    if title is None:
        raise ConversionError("o OCR não encontrou um título confiável")
    selected_author = author or values.get("author")
    if selected_author is None:
        raise ConversionError("o autor não foi confirmado; informe --author")
    display_title = report.source.stem
    if " [" in display_title:
        display_title = display_title.split(" [", maxsplit=1)[0]
    volume_text = values.get("volume")
    return ComicMetadata(
        title=display_title,
        authors=(selected_author,),
        series=title,
        volume=float(volume_text) if volume_text is not None else None,
        isbn=values.get("isbn"),
        publisher=publisher or values.get("publisher"),
        tags=tags,
    )


def create_metadata_cbr(source: Path, output: Path, metadata: ComicMetadata, *, rar: str = "rar") -> Path:
    """Cria uma cópia CBR com comentário ComicBookInfo, sem alterar a origem."""
    original = source.resolve(strict=True)
    destination = output.resolve()
    if detect_archive_format(original) != "rar":
        raise ConversionError(f"o conteúdo não é RAR: {original}")
    if destination.suffix.casefold() != ".cbr":
        raise ConversionError("o arquivo de saída deve usar a extensão .cbr")
    if destination.exists():
        raise ConversionError(f"o arquivo de saída já existe: {destination}")
    if shutil.which(rar) is None:
        raise ConversionError("o executável rar não foi encontrado")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    comment_path: Path | None = None
    try:
        shutil.copyfile(original, temporary)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as comment_file:
            comment_file.write(metadata.to_comment())
            comment_path = Path(comment_file.name)
        _run_rar([rar, "c", f"-z{comment_path}", "-inul", "-p-", "--", os.fspath(temporary)])
        inspect_rar(temporary)
        if read_rar_comment(temporary, rar=rar) != metadata.to_comment():
            raise ConversionError("os metadados gravados no CBR não correspondem ao conteúdo solicitado")
        _publish_without_overwrite(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if comment_path is not None:
            comment_path.unlink(missing_ok=True)
    return destination


def read_rar_comment(path: Path, *, rar: str = "rar") -> str:
    """Lê o comentário do RAR pelo utilitário oficial."""
    result = _run_rar([rar, "cw", "-inul", "-p-", "--", os.fspath(path)])
    return result.stdout.decode("utf-8", errors="strict").strip()


def _run_rar(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(command, check=False, capture_output=True)
    except FileNotFoundError as error:
        raise ConversionError("o executável rar não foi encontrado") from error
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or f"código {result.returncode}"
        raise ConversionError(f"falha ao manipular metadados RAR: {detail}")
    return result


def _publish_without_overwrite(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ConversionError(f"o arquivo de saída já existe: {destination}") from error
    temporary.unlink()
