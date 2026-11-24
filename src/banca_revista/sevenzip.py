"""Leitura de quadrinhos em 7-Zip (CB7), inclusive disfarçados com extensão ``.cbr``.

Arquivos 7-Zip costumam ser sólidos: ler uma página isolada descompacta o bloco desde o início. Por isso as páginas
são extraídas de uma vez numa pasta temporária isolada, depois de validar os nomes listados.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from banca_revista.archive import (
    ArchiveInspection,
    ConversionError,
    MemberStream,
    detect_archive_format,
    plan_pages,
)

# Senha fixa e falsa: um arquivo cifrado falha em vez de o 7z esperar a senha no terminal.
_NO_PASSWORD = "-p__banca_sem_senha__"
_PASSWORD_HINTS = ("wrong password", "can not open encrypted archive", "cannot open encrypted archive")


def inspect_7z(path: Path, *, sevenzip: str = "7z", flatten: bool = True) -> ArchiveInspection:
    """Testa a integridade e lista as páginas sem escrever nada."""
    source = path.resolve(strict=True)
    if detect_archive_format(source) != "7z":
        raise ConversionError(f"o conteúdo não é 7z: {source}")
    _run_7z([sevenzip, "t", "-bd", "-bso0", "-bsp0", _NO_PASSWORD, "--", os.fspath(source)])
    pages, common_parent = plan_pages(list_7z_entries(source, sevenzip=sevenzip), flatten=flatten)
    return ArchiveInspection(source=source, archive_format="7z", pages=pages, common_parent=common_parent)


def list_7z_entries(path: Path, *, sevenzip: str = "7z") -> tuple[str, ...]:
    """Lista os arquivos (não as pastas) e recusa qualquer entrada cifrada."""
    listing = _run_7z([sevenzip, "l", "-slt", "-ba", _NO_PASSWORD, "--", os.fspath(path)])
    names: list[str] = []
    for block in listing.split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" not in fields:
            continue
        if fields.get("Encrypted") == "+":
            raise ConversionError(f"7z protegido por senha: {fields['Path']!r}")
        # "Attributes = A lrwxrwxrwx": atributos Windows e, depois, o modo Unix quando o 7z o registrou.
        windows, _, unix = fields.get("Attributes", "").partition(" ")
        if unix.startswith("l"):
            raise ConversionError(f"entrada do 7z é um link simbólico: {fields['Path']!r}")
        if fields.get("Folder") != "+" and "D" not in windows and not unix.startswith("d"):
            names.append(fields["Path"])
    return tuple(names)


def extract_7z_pages(inspection: ArchiveInspection, destination: Path, *, sevenzip: str = "7z") -> list[Path]:
    """Extrai tudo em ``destination`` (pasta vazia e isolada) e devolve as páginas na ordem planejada."""
    target = destination.resolve(strict=True)
    if any(target.iterdir()):
        raise ConversionError(f"a pasta de extração do 7z não está vazia: {target}")
    _run_7z(
        [sevenzip, "x", "-bd", "-bso0", "-bsp0", "-y", _NO_PASSWORD, f"-o{target}", "--", os.fspath(inspection.source)]
    )
    pages: list[Path] = []
    for page in inspection.pages:
        path = target / page.source_name
        if path.is_symlink():
            raise ConversionError(f"página do 7z é um link simbólico: {page.source_name!r}")
        if not path.resolve().is_relative_to(target) or not path.is_file():
            raise ConversionError(f"página do 7z não foi extraída como arquivo: {page.source_name!r}")
        pages.append(path)
    return pages


def open_7z_member(source: Path, name: str, *, sevenzip: str = "7z") -> MemberStream:
    """Abre um membro como stream; ``-spd`` impede que ``*`` ou ``?`` no nome virem curinga."""
    try:
        process = subprocess.Popen(
            [sevenzip, "e", "-so", "-spd", "-bd", _NO_PASSWORD, "--", os.fspath(source), name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise ConversionError("o executável 7z não foi encontrado") from error
    return MemberStream(process, name)


def _run_7z(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise ConversionError("o executável 7z não foi encontrado") from error
    if result.returncode == 0:
        return result.stdout
    detail = result.stderr.strip() or result.stdout.strip() or f"código {result.returncode}"
    if any(hint in detail.casefold() for hint in _PASSWORD_HINTS):
        raise ConversionError(f"7z protegido por senha: {detail}")
    raise ConversionError(f"falha ao ler o 7z: {detail}")
