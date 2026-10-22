"""Inspeção e extração de ZIP/RAR que agrupam quadrinhos (CBR, CBZ ou PDF)."""

from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from banca_revista.archive import (
    IMAGE_EXTENSIONS,
    PDF_SIGNATURE,
    ConversionError,
    detect_archive_format,
    list_rar_entries,
    natural_key,
    open_rar_member,
)

COMIC_EXTENSIONS = frozenset({".cbr", ".cbz", ".pdf"})


@dataclass(frozen=True)
class ContainerInspection:
    """ZIP ou RAR cujo conteúdo são quadrinhos, não páginas."""

    source: Path
    archive_format: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedComic:
    """Quadrinho publicado ao lado do contêiner; ``reused`` indica arquivo idêntico preexistente."""

    member: str
    path: Path
    reused: bool


def find_comic_entries(names: Iterable[str]) -> tuple[str, ...]:
    """Seleciona CBR/CBZ/PDF em ordem natural; vazio significa quadrinho comum (há imagens ou nada)."""
    comics: list[str] = []
    has_images = False
    targets: dict[str, str] = {}
    for raw_name in names:
        path = PurePosixPath(raw_name.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ConversionError(f"entrada insegura no arquivo: {raw_name!r}")
        if raw_name.endswith(("/", "\\")) or "__MACOSX" in path.parts:
            continue
        suffix = path.suffix.casefold()
        if suffix in IMAGE_EXTENSIONS:
            has_images = True
        elif suffix in COMIC_EXTENSIONS:
            comics.append(raw_name)
    if has_images:
        # Imagens mandam: o arquivo é um quadrinho comum e o fluxo de conversão decide sobre os extras.
        return ()
    for raw_name in comics:
        key = PurePosixPath(raw_name.replace("\\", "/")).stem.casefold()
        if key in targets:
            raise ConversionError(f"quadrinhos produziriam a mesma saída: {targets[key]!r} e {raw_name!r}")
        targets[key] = raw_name
    comics.sort(key=natural_key)
    return tuple(comics)


def inspect_container(path: Path, *, unrar: str = "unrar") -> ContainerInspection | None:
    """Lista o conteúdo sem escrever nada; ``None`` quando não há quadrinhos dentro."""
    source = path.resolve(strict=True)
    archive_format = detect_archive_format(source)
    if archive_format == "zip":
        try:
            with zipfile.ZipFile(source) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile as error:
            raise ConversionError(f"ZIP corrompido: {error}") from error
    else:
        names = list_rar_entries(source, unrar=unrar)
    members = find_comic_entries(names)
    if not members:
        return None
    return ContainerInspection(source=source, archive_format=archive_format, members=members)


def extract_container(
    inspection: ContainerInspection,
    destination_dir: Path,
    *,
    unrar: str = "unrar",
) -> tuple[ExtractedComic, ...]:
    """Extrai cada quadrinho de forma atômica, sem sobrescrever nem alterar o contêiner."""
    destination = destination_dir.resolve(strict=True)
    extracted: list[ExtractedComic] = []
    if inspection.archive_format == "zip":
        with zipfile.ZipFile(inspection.source) as archive:
            for member in inspection.members:
                if archive.getinfo(member).flag_bits & 0x1:
                    raise ConversionError(f"quadrinho protegido por senha no ZIP: {member}")
                extracted.append(_extract_member(partial(archive.open, member), member, destination))
    else:
        for member in inspection.members:
            opener = partial(open_rar_member, inspection.source, member, unrar=unrar)
            extracted.append(_extract_member(opener, member, destination))
    return tuple(extracted)


def _extract_member(
    open_stream: Callable[[], AbstractContextManager[BinaryIO]],
    member: str,
    destination_dir: Path,
) -> ExtractedComic:
    target = destination_dir / PurePosixPath(member.replace("\\", "/")).name
    descriptor, temporary_name = tempfile.mkstemp(prefix=".banca-", suffix=".tmp", dir=destination_dir)
    temporary = Path(temporary_name)
    try:
        digest = hashlib.sha256()
        # O stream precisa fechar antes da publicação: é no fechamento que o unrar informa erro de CRC.
        try:
            with os.fdopen(descriptor, "wb") as output, open_stream() as stream:
                while chunk := stream.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as error:
            if isinstance(error, ConversionError):
                raise
            raise ConversionError(f"falha ao extrair {member!r}: {error}") from error
        _validate_comic(temporary, member)
        try:
            os.link(temporary, target)
        except FileExistsError:
            if _sha256(target) != digest.hexdigest():
                raise ConversionError(f"{target.name} já existe com conteúdo diferente em {destination_dir}") from None
            return ExtractedComic(member=member, path=target, reused=True)
        return ExtractedComic(member=member, path=target, reused=False)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_comic(path: Path, member: str) -> None:
    if PurePosixPath(member).suffix.casefold() == ".pdf":
        with path.open("rb") as stream:
            if not stream.read(len(PDF_SIGNATURE)).startswith(PDF_SIGNATURE):
                raise ConversionError(f"o conteúdo de {member!r} não é PDF")
        return
    try:
        detect_archive_format(path)
    except ConversionError as error:
        raise ConversionError(f"o conteúdo de {member!r} não é ZIP nem RAR") from error
