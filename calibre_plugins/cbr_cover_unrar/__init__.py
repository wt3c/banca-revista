"""Leitor de capas CBR para instalações do Calibre sem ``unrardll`` funcional."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

from calibre.customize import MetadataReaderPlugin
from calibre.ebooks.metadata import MetaInformation

IMAGE_EXTENSIONS = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})
NATURAL_PART = re.compile(r"(\d+)")


def natural_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Ordena nomes de páginas numericamente e sem depender do locale."""
    parts: list[tuple[int, int | str]] = []
    for part in NATURAL_PART.split(name.casefold()):
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts)


def first_image(names: list[str]) -> str:
    """Retorna a primeira imagem válida do arquivo na ordenação natural."""
    images = []
    for name in names:
        normalized = name.replace("\\", "/")
        path = Path(normalized)
        if path.name.casefold() == "thumbs.db" or "__MACOSX" in path.parts:
            continue
        if path.suffix.casefold() in IMAGE_EXTENSIONS:
            images.append(name)
    if not images:
        raise ValueError("o CBR não contém uma imagem de capa compatível")
    return min(images, key=natural_key)


def run_unrar(arguments: list[str], *, binary: bool = False) -> bytes | str:
    """Executa o unrar do sistema e converte erros em falhas do plugin."""
    executable = shutil.which("unrar")
    if executable is None:
        raise RuntimeError("o executável unrar não foi encontrado no PATH")
    result = subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() or f"código {result.returncode}"
        raise RuntimeError(f"falha ao ler o CBR com unrar: {detail}")
    if binary:
        return result.stdout
    return result.stdout.decode(sys.getfilesystemencoding(), errors="surrogateescape")


def read_comic_metadata(archive: Path, metadata) -> None:
    """Lê o ComicBookInfo gravado como comentário do RAR."""
    executable = shutil.which("rar")
    if executable is None:
        return
    result = subprocess.run(
        [executable, "cw", "-inul", "-p-", "--", os.fspath(archive)],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return
    try:
        document = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return
    if not isinstance(document, dict):
        return
    book = next((value for key, value in document.items() if key.startswith("ComicBookInfo")), None)
    if not isinstance(book, dict):
        return

    for field in ("title", "publisher", "comments"):
        value = book.get(field)
        if isinstance(value, str) and value.strip():
            setattr(metadata, field, value.strip())
    series = book.get("series")
    if isinstance(series, str) and series.strip():
        metadata.series = series.strip()
    volume = book.get("volume")
    if isinstance(volume, (int, float)):
        metadata.series_index = float(volume)
    isbn = book.get("isbn")
    if isinstance(isbn, str) and isbn.strip():
        metadata.isbn = isbn.strip()
    tags = book.get("tags")
    if isinstance(tags, list):
        metadata.tags = [tag.strip() for tag in tags if isinstance(tag, str) and tag.strip()]
    credits = book.get("credits")
    if isinstance(credits, list):
        authors = [
            credit["person"].strip()
            for credit in credits
            if isinstance(credit, dict)
            and credit.get("role") in {"Writer", "Artist", "Cartoonist", "Creator"}
            and isinstance(credit.get("person"), str)
            and credit["person"].strip()
        ]
        if authors:
            metadata.authors = authors


@contextmanager
def stream_path(stream):
    """Fornece ao unrar um caminho real sem alterar permanentemente o stream."""
    stream_name = getattr(stream, "name", None)
    if stream_name:
        candidate = Path(stream_name)
        if candidate.is_file():
            yield candidate
            return

    position = stream.tell() if hasattr(stream, "tell") else None
    descriptor, temporary_name = tempfile.mkstemp(suffix=".cbr")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if hasattr(stream, "seek"):
            stream.seek(0)
        with temporary.open("wb") as destination:
            shutil.copyfileobj(stream, destination)
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)
        if position is not None and hasattr(stream, "seek"):
            stream.seek(position)


class CbrCoverUnrar(MetadataReaderPlugin):
    """Extrai automaticamente a capa de CBR usando o unrar do sistema."""

    name = "CBR cover via system unrar"
    author = "Banca Revista"
    description = "Extract CBR covers with the system unrar command"
    version = (1, 1, 0)
    minimum_calibre_version = (6, 0, 0)
    file_types: ClassVar[set[str]] = {"cbr"}

    def get_metadata(self, stream, type):
        metadata = MetaInformation(None, None)
        with stream_path(stream) as archive:
            archive_name = os.fspath(archive)
            listing = run_unrar(["lb", "-p-", "--", archive_name])
            names = [line for line in listing.splitlines() if line]
            cover_name = first_image(names)
            cover = run_unrar(["p", "-inul", "-p-", "--", archive_name, cover_name], binary=True)
            read_comic_metadata(archive, metadata)

        extension = Path(cover_name).suffix.removeprefix(".").lower()
        metadata.cover_data = (extension, cover)
        return metadata
