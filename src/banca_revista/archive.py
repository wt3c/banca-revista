"""Inspeção e normalização de arquivos de quadrinhos."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol

RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
IMAGE_EXTENSIONS = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})
_NATURAL_PART = re.compile(r"(\d+)")


class ConversionError(RuntimeError):
    """Erro esperado ao inspecionar ou converter um quadrinho."""


class Digest(Protocol):
    """Contrato mínimo usado durante a cópia de uma página."""

    def update(self, data: bytes, /) -> None: ...


@dataclass(frozen=True)
class Page:
    """Uma página selecionada no arquivo de origem."""

    source_name: str
    output_name: str


@dataclass(frozen=True)
class ArchiveInspection:
    """Plano imutável produzido pela inspeção de um arquivo."""

    source: Path
    archive_format: str
    pages: tuple[Page, ...]
    common_parent: str | None


@dataclass(frozen=True)
class ConversionResult:
    """Resumo verificável de uma conversão concluída."""

    source: Path
    output: Path
    page_count: int
    first_page: str
    sha256_by_page: dict[str, str]


def detect_archive_format(path: Path) -> str:
    """Detecta RAR ou ZIP pelo cabeçalho, sem confiar na extensão."""
    with path.open("rb") as stream:
        signature = stream.read(max(len(RAR5_SIGNATURE), 4))
    if signature.startswith((RAR4_SIGNATURE, RAR5_SIGNATURE)):
        return "rar"
    if signature.startswith(ZIP_SIGNATURES):
        return "zip"
    raise ConversionError(f"formato de arquivo não suportado: {path}")


def natural_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Produz uma ordenação natural, determinística e sem dependência de locale."""
    parts: list[tuple[int, int | str]] = []
    for part in _NATURAL_PART.split(name.casefold()):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts)


def plan_pages(names: Iterable[str], *, flatten: bool = True) -> tuple[tuple[Page, ...], str | None]:
    """Valida entradas e planeja páginas achatadas ou com caminho preservado."""
    image_paths: list[PurePosixPath] = []
    for raw_name in names:
        normalized = raw_name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ConversionError(f"entrada insegura no arquivo: {raw_name!r}")
        if path.suffix.casefold() in IMAGE_EXTENSIONS:
            image_paths.append(path)

    if not image_paths:
        raise ConversionError("nenhuma imagem compatível foi encontrada no arquivo")

    output_names: dict[str, str] = {}
    pages: list[Page] = []
    for path in image_paths:
        output_name = path.name if flatten else str(path)
        collision_key = output_name.casefold()
        if collision_key in output_names:
            previous = output_names[collision_key]
            raise ConversionError(f"nomes de página colidem ao achatar o arquivo: {previous!r} e {str(path)!r}")
        output_names[collision_key] = str(path)
        pages.append(Page(source_name=str(path), output_name=output_name))

    pages.sort(key=lambda page: natural_key(page.output_name))
    parents = {str(path.parent) for path in image_paths}
    common_parent = parents.pop() if len(parents) == 1 and parents != {"."} else None
    return tuple(pages), common_parent


def inspect_rar(path: Path, *, unrar: str = "unrar", flatten: bool = True) -> ArchiveInspection:
    """Testa a integridade e lista as páginas de um RAR sem extraí-lo."""
    source = path.resolve(strict=True)
    if detect_archive_format(source) != "rar":
        raise ConversionError(f"o conteúdo não é RAR: {source}")

    _run_unrar([unrar, "t", "-idq", "-p-", "--", os.fspath(source)])
    listing = _run_unrar([unrar, "lb", "-p-", "--", os.fspath(source)])
    names = tuple(line for line in listing.stdout.splitlines() if line)
    pages, common_parent = plan_pages(names, flatten=flatten)
    return ArchiveInspection(source=source, archive_format="rar", pages=pages, common_parent=common_parent)


def convert_rar_to_cbz(
    inspection: ArchiveInspection,
    output: Path,
    *,
    unrar: str = "unrar",
    extractor: Callable[[Path, str], BinaryIO] | None = None,
) -> ConversionResult:
    """Cria um CBZ atômico, achatado e validado sem modificar a origem."""
    if inspection.archive_format != "rar":
        raise ConversionError("a inspeção fornecida não representa um arquivo RAR")

    destination = output.resolve()
    if destination.suffix.casefold() != ".cbz":
        raise ConversionError("o arquivo de saída deve usar a extensão .cbz")
    if destination.exists():
        raise ConversionError(f"o arquivo de saída já existe: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    read_member = extractor or (lambda source, name: open_rar_member(source, name, unrar=unrar))
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    hashes: dict[str, str] = {}

    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for page in inspection.pages:
                digest = hashlib.sha256()
                with (
                    read_member(inspection.source, page.source_name) as source_stream,
                    archive.open(page.output_name, "w") as destination_stream,
                ):
                    _copy_and_hash(source_stream, destination_stream, digest)
                hashes[page.output_name] = digest.hexdigest()

        _validate_cbz(temporary, inspection.pages, hashes)
        _publish_without_overwrite(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return ConversionResult(
        source=inspection.source,
        output=destination,
        page_count=len(inspection.pages),
        first_page=inspection.pages[0].output_name,
        sha256_by_page=hashes,
    )


def _copy_and_hash(source: BinaryIO, destination: BinaryIO, digest: Digest) -> None:
    while chunk := source.read(1024 * 1024):
        destination.write(chunk)
        digest.update(chunk)


def _validate_cbz(path: Path, pages: tuple[Page, ...], expected_hashes: dict[str, str]) -> None:
    expected_names = [page.output_name for page in pages]
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ConversionError("o CBZ gerado falhou na validação CRC")
        if archive.namelist() != expected_names:
            raise ConversionError("a ordem das páginas mudou durante a criação do CBZ")
        for name in expected_names:
            digest = hashlib.sha256(archive.read(name)).hexdigest()
            if digest != expected_hashes[name]:
                raise ConversionError(f"o conteúdo da página mudou durante a conversão: {name}")


def _publish_without_overwrite(temporary: Path, destination: Path) -> None:
    """Publica no mesmo filesystem sem uma janela de sobrescrita acidental."""
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ConversionError(f"o arquivo de saída já existe: {destination}") from error
    temporary.unlink()


def _run_unrar(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ConversionError("o executável unrar não foi encontrado") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or f"código {error.returncode}"
        raise ConversionError(f"falha ao ler o RAR: {detail}") from error


class _UnrarMemberStream:
    def __init__(self, process: subprocess.Popen[bytes], name: str) -> None:
        self.process = process
        self.name = name
        if process.stdout is None:
            raise ConversionError("o unrar não disponibilizou a saída da página")
        self.stdout = process.stdout

    def __enter__(self) -> BinaryIO:
        return self.stdout

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.stdout.close()
        stderr = self.process.stderr.read() if self.process.stderr is not None else b""
        return_code = self.process.wait()
        if exc_type is None and return_code != 0:
            detail = stderr.decode(errors="replace").strip() or f"código {return_code}"
            raise ConversionError(f"falha ao extrair {self.name!r}: {detail}")


def open_rar_member(source: Path, name: str, *, unrar: str = "unrar") -> _UnrarMemberStream:
    """Abre um membro do RAR como stream sem extraí-lo para o filesystem."""
    try:
        process = subprocess.Popen(
            [unrar, "p", "-inul", "-p-", "--", os.fspath(source), name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise ConversionError("o executável unrar não foi encontrado") from error
    return _UnrarMemberStream(process, name)
