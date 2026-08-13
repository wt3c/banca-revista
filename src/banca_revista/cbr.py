"""Conversão segura de PDF e ZIP para CBR verdadeiro."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from banca_revista.archive import (
    IMAGE_EXTENSIONS,
    RAR4_SIGNATURE,
    RAR5_SIGNATURE,
    ZIP_SIGNATURES,
    ConversionError,
    detect_archive_format,
    inspect_rar,
    natural_key,
    open_rar_member,
)
from banca_revista.metadata import ComicMetadata, parse_comic_metadata, read_rar_comment

PDF_SIGNATURE = b"%PDF-"
_IGNORED_ZIP_EXTENSIONS = frozenset({".diz", ".nfo", ".txt", ".xml"})


@dataclass(frozen=True)
class PdfInspection:
    """Informações necessárias para escolher extração ou renderização."""

    page_count: int
    title: str | None
    author: str | None
    encrypted: bool
    lossless_images: bool


@dataclass(frozen=True)
class PdfImage:
    """Imagem enumerada pelo Poppler."""

    page: int
    image_type: str
    encoding: str


@dataclass(frozen=True)
class CbrConversionResult:
    """Resumo verificável de uma conversão concluída."""

    source: Path
    output: Path
    input_format: str
    page_count: int
    first_page: str
    strategy: str


def detect_cbr_source(path: Path) -> str:
    """Detecta PDF ou ZIP pelo cabeçalho, sem confiar na extensão."""
    with path.open("rb") as stream:
        signature = stream.read(8)
    if signature.startswith(PDF_SIGNATURE):
        return "pdf"
    if signature.startswith(ZIP_SIGNATURES):
        return "zip"
    if signature.startswith((RAR4_SIGNATURE, RAR5_SIGNATURE)):
        return "rar"
    raise ConversionError(f"a origem não é PDF, ZIP nem RAR: {path}")


def convert_to_cbr(
    source: Path,
    output: Path,
    *,
    pdf_mode: str = "auto",
    dpi: int = 200,
    rar: str = "rar",
    unrar: str = "unrar",
    pdfinfo: str = "pdfinfo",
    pdfimages: str = "pdfimages",
    pdftoppm: str = "pdftoppm",
) -> CbrConversionResult:
    """Converte PDF ou ZIP em novo CBR atômico, preservando a origem."""
    original = source.resolve(strict=True)
    destination = output.resolve()
    input_format = detect_cbr_source(original)
    _validate_destination(destination)
    if pdf_mode not in {"auto", "lossless", "render"}:
        raise ConversionError("pdf_mode deve ser auto, lossless ou render")
    if not 72 <= dpi <= 600:
        raise ConversionError("o DPI deve estar entre 72 e 600")
    _require_executable(rar)
    _require_executable(unrar)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.stem}-", dir=destination.parent) as temporary_name:
        temporary = Path(temporary_name)
        pages_dir = temporary / "pages"
        pages_dir.mkdir()
        if input_format == "pdf":
            inspection = inspect_pdf(original, pdfinfo=pdfinfo, pdfimages=pdfimages)
            staged, hashes, strategy = _stage_pdf(
                original,
                inspection,
                pages_dir,
                mode=pdf_mode,
                dpi=dpi,
                pdfimages=pdfimages,
                pdftoppm=pdftoppm,
            )
            metadata = ComicMetadata(
                title=inspection.title or original.stem,
                authors=(inspection.author,) if inspection.author else (),
            )
        elif input_format == "zip":
            staged, hashes, strategy = _stage_zip(original, pages_dir, unrar=unrar)
            metadata = ComicMetadata(title=original.stem)
        else:
            staged, hashes = _stage_rar(original, pages_dir, unrar=unrar)
            strategy = "cbr-normalized"
            metadata = _read_existing_metadata(original, fallback_title=original.stem, rar=rar)

        archive = temporary / "result.rar"
        _create_rar(archive, staged, metadata, rar=rar, temporary=temporary)
        _validate_cbr(archive, staged, hashes, unrar=unrar)
        _publish_without_overwrite(archive, destination)

    return CbrConversionResult(
        source=original,
        output=destination,
        input_format=input_format,
        page_count=len(staged),
        first_page=staged[0].name,
        strategy=strategy,
    )


def inspect_pdf(path: Path, *, pdfinfo: str = "pdfinfo", pdfimages: str = "pdfimages") -> PdfInspection:
    """Inspeciona PDF e decide se uma imagem JPEG integral existe por página."""
    _require_executable(pdfinfo)
    _require_executable(pdfimages)
    info_result = _run([pdfinfo, os.fspath(path)], tool="pdfinfo", text=True)
    info = _parse_key_values(info_result.stdout)
    try:
        page_count = int(info["Pages"])
    except (KeyError, ValueError) as error:
        raise ConversionError("pdfinfo não informou uma quantidade válida de páginas") from error
    if page_count < 1:
        raise ConversionError("o PDF não possui páginas")
    encrypted = info.get("Encrypted", "no").casefold() != "no"
    image_result = _run([pdfimages, "-list", os.fspath(path)], tool="pdfimages", text=True)
    images = parse_pdfimages_list(image_result.stdout)
    lossless = pdf_lossless_eligible(page_count, images)
    return PdfInspection(
        page_count=page_count,
        title=info.get("Title") or None,
        author=info.get("Author") or None,
        encrypted=encrypted,
        lossless_images=lossless,
    )


def parse_pdfimages_list(output: str) -> tuple[PdfImage, ...]:
    """Analisa a tabela estável produzida por ``pdfimages -list``."""
    images: list[PdfImage] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 9 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        images.append(PdfImage(page=int(fields[0]), image_type=fields[2].casefold(), encoding=fields[8].casefold()))
    return tuple(images)


def pdf_lossless_eligible(page_count: int, images: tuple[PdfImage, ...]) -> bool:
    """Exige exatamente uma imagem JPEG normal para cada página."""
    return len(images) == page_count and all(
        image.page == index and image.image_type == "image" and image.encoding == "jpeg"
        for index, image in enumerate(images, start=1)
    )


def classify_zip_entries(names: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    """Classifica ZIP de imagens ou coleção de CBRs e rejeita mistura ambígua."""
    images: list[str] = []
    comics: list[str] = []
    unexpected: list[str] = []
    for raw_name in names:
        normalized = raw_name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ConversionError(f"entrada insegura no ZIP: {raw_name!r}")
        if raw_name.endswith("/") or "__MACOSX" in path.parts or path.name.casefold() == "thumbs.db":
            continue
        suffix = path.suffix.casefold()
        if suffix in IMAGE_EXTENSIONS:
            images.append(raw_name)
        elif suffix == ".cbr":
            comics.append(raw_name)
        elif suffix not in _IGNORED_ZIP_EXTENSIONS:
            unexpected.append(raw_name)
    if unexpected or (images and comics):
        detail = unexpected[0] if unexpected else "imagens e CBRs no mesmo ZIP"
        raise ConversionError(f"conteúdo ZIP ambíguo: {detail}")
    selected = images or comics
    if not selected:
        raise ConversionError("o ZIP não contém imagens nem arquivos CBR")
    selected.sort(key=natural_key)
    return ("images" if images else "nested-cbr"), tuple(selected)


def _stage_pdf(
    source: Path,
    inspection: PdfInspection,
    pages_dir: Path,
    *,
    mode: str,
    dpi: int,
    pdfimages: str,
    pdftoppm: str,
) -> tuple[list[Path], dict[str, str], str]:
    if inspection.encrypted:
        raise ConversionError("PDF protegido por senha não é suportado")
    use_lossless = inspection.lossless_images and mode != "render"
    if mode == "lossless" and not inspection.lossless_images:
        raise ConversionError("o PDF não possui exatamente uma imagem JPEG por página")
    extracted_dir = pages_dir.parent / "pdf-extracted"
    extracted_dir.mkdir()
    prefix = extracted_dir / "page"
    if use_lossless:
        _run([pdfimages, "-j", os.fspath(source), os.fspath(prefix)], tool="pdfimages")
        strategy = "pdf-lossless"
    else:
        _require_executable(pdftoppm)
        _run(
            [
                pdftoppm,
                "-jpeg",
                "-r",
                str(dpi),
                "-jpegopt",
                "quality=92,optimize=y",
                os.fspath(source),
                os.fspath(prefix),
            ],
            tool="pdftoppm",
        )
        strategy = f"pdf-render-{dpi}dpi"
    extracted = sorted(
        (path for path in extracted_dir.iterdir() if path.is_file()), key=lambda path: natural_key(path.name)
    )
    if len(extracted) != inspection.page_count:
        raise ConversionError(
            f"o PDF possui {inspection.page_count} páginas, mas a conversão produziu {len(extracted)} imagens"
        )
    return (*_stage_files(extracted, pages_dir), strategy)


def _stage_zip(source: Path, pages_dir: Path, *, unrar: str) -> tuple[list[Path], dict[str, str], str]:
    staged: list[Path] = []
    hashes: dict[str, str] = {}
    with zipfile.ZipFile(source) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise ConversionError(f"o ZIP falhou na validação CRC: {bad_member}")
        mode, entries = classify_zip_entries(info.filename for info in archive.infolist())
        if mode == "images":
            for name in entries:
                with archive.open(name) as stream:
                    _stage_stream(stream, Path(name).suffix, pages_dir, staged, hashes)
            return staged, hashes, "zip-images"

        nested_dir = pages_dir.parent / "nested"
        nested_dir.mkdir()
        for issue_index, name in enumerate(entries, start=1):
            nested = nested_dir / f"issue-{issue_index:04}.cbr"
            with archive.open(name) as source_stream, nested.open("wb") as destination:
                shutil.copyfileobj(source_stream, destination)
            if detect_archive_format(nested) != "rar":
                raise ConversionError(f"o CBR interno não contém RAR: {name}")
            inspection = inspect_rar(nested, unrar=unrar, flatten=False)
            for page in inspection.pages:
                with open_rar_member(nested, page.source_name, unrar=unrar) as stream:
                    _stage_stream(stream, Path(page.output_name).suffix, pages_dir, staged, hashes)
        return staged, hashes, "zip-nested-cbr"


def _stage_rar(source: Path, pages_dir: Path, *, unrar: str) -> tuple[list[Path], dict[str, str]]:
    staged: list[Path] = []
    hashes: dict[str, str] = {}
    inspection = inspect_rar(source, unrar=unrar, flatten=False)
    for page in inspection.pages:
        with open_rar_member(source, page.source_name, unrar=unrar) as stream:
            _stage_stream(stream, Path(page.output_name).suffix, pages_dir, staged, hashes)
    return staged, hashes


def _stage_files(files: list[Path], pages_dir: Path) -> tuple[list[Path], dict[str, str]]:
    staged: list[Path] = []
    hashes: dict[str, str] = {}
    for source in files:
        with source.open("rb") as stream:
            _stage_stream(stream, source.suffix, pages_dir, staged, hashes)
    return staged, hashes


def _stage_stream(
    stream: BinaryIO,
    extension: str,
    pages_dir: Path,
    staged: list[Path],
    hashes: dict[str, str],
) -> None:
    suffix = extension.casefold()
    if suffix not in IMAGE_EXTENSIONS:
        raise ConversionError(f"formato de imagem não suportado: {extension}")
    destination = pages_dir / f"{len(staged) + 1:06d}{suffix}"
    digest = hashlib.sha256()
    with destination.open("wb") as output:
        while chunk := stream.read(1024 * 1024):
            output.write(chunk)
            digest.update(chunk)
    if destination.stat().st_size == 0:
        raise ConversionError(f"imagem vazia encontrada: {destination.name}")
    staged.append(destination)
    hashes[destination.name] = digest.hexdigest()


def _create_rar(archive: Path, pages: list[Path], metadata: ComicMetadata, *, rar: str, temporary: Path) -> None:
    comment = temporary / "ComicBookInfo.json"
    comment.write_text(metadata.to_comment(), encoding="utf-8")
    command = [
        rar,
        "a",
        "-ma5",
        "-m0",
        "-idq",
        "-ep1",
        f"-z{comment}",
        "--",
        os.fspath(archive),
        *(os.fspath(page) for page in pages),
    ]
    _run(command, tool="rar")
    if not archive.is_file():
        raise ConversionError("o rar não criou o arquivo CBR esperado")


def _validate_cbr(archive: Path, pages: list[Path], expected_hashes: dict[str, str], *, unrar: str) -> None:
    inspection = inspect_rar(archive, unrar=unrar)
    _validate_unencrypted(archive, inspection.pages[0].source_name, unrar=unrar)
    expected_names = [page.name for page in pages]
    actual_names = [page.output_name for page in inspection.pages]
    if actual_names != expected_names:
        raise ConversionError("a ordem ou os nomes das páginas mudaram durante a criação do CBR")
    for name in actual_names:
        digest = hashlib.sha256()
        with open_rar_member(archive, name, unrar=unrar) as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected_hashes[name]:
            raise ConversionError(f"o conteúdo da página mudou durante a criação do CBR: {name}")


def _validate_unencrypted(archive: Path, first_page: str, *, unrar: str) -> None:
    """Confirma que uma senha arbitrária não é necessária para ler a primeira página."""
    try:
        result = subprocess.run(
            [unrar, "p", "-inul", "-p__banca_sem_senha__", "--", os.fspath(archive), first_page],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError as error:
        raise ConversionError("o executável unrar não foi encontrado") from error
    if result.returncode != 0:
        raise ConversionError("o CBR gerado está protegido por senha")


def _validate_destination(destination: Path) -> None:
    if destination.suffix.casefold() != ".cbr":
        raise ConversionError("o arquivo de saída deve usar a extensão .cbr")
    if destination.exists():
        raise ConversionError(f"o arquivo de saída já existe: {destination}")


def _parse_key_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


def _run(command: list[str], *, tool: str, text: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=text)
    except FileNotFoundError as error:
        raise ConversionError(f"o executável {tool} não foi encontrado") from error
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode(errors="replace")
        stdout = result.stdout if text else result.stdout.decode(errors="replace")
        detail = stderr.strip() or stdout.strip() or f"código {result.returncode}"
        raise ConversionError(f"falha ao executar {tool}: {detail}")
    return result


def _require_executable(executable: str) -> None:
    if shutil.which(executable) is None:
        raise ConversionError(f"o executável {executable} não foi encontrado")


def _publish_without_overwrite(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError as error:
        raise ConversionError(f"o arquivo de saída já existe: {destination}") from error


def _read_existing_metadata(source: Path, *, fallback_title: str, rar: str) -> ComicMetadata:
    try:
        parsed = parse_comic_metadata(read_rar_comment(source, rar=rar))
    except (ConversionError, UnicodeDecodeError):
        parsed = None
    return parsed or ComicMetadata(title=fallback_title)
