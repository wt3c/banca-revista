"""Envio de originais para a Lixeira do usuário (especificação freedesktop.org), sem apagar nem sobrescrever."""

from __future__ import annotations

import os
from datetime import datetime
from itertools import count
from pathlib import Path
from urllib.parse import quote


def default_trash_dir() -> Path:
    """Lixeira em ``$XDG_DATA_HOME/Trash``, a mesma usada pelo gerenciador de arquivos."""
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "Trash"


def move_to_trash(path: Path, trash_dir: Path | None = None) -> Path:
    """Move o arquivo com ``.trashinfo`` restaurável; exige a mesma partição e nunca copia."""
    source = path.absolute()
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError(f"não é um arquivo regular: {source}")
    trash = trash_dir or default_trash_dir()
    files_dir = trash / "files"
    info_dir = trash / "info"
    files_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    info_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in _candidate_names(source.name):
        info = info_dir / f"{name}.trashinfo"
        try:
            # O .trashinfo criado com O_EXCL reserva o nome antes de mover o arquivo, como pede a especificação.
            descriptor = os.open(info, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        target = files_dir / name
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write("[Trash Info]\n")
                stream.write(f"Path={quote(os.fspath(source))}\n")
                stream.write(f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
            os.link(source, target)
        except FileExistsError:
            info.unlink(missing_ok=True)
            continue
        except BaseException:
            info.unlink(missing_ok=True)
            raise
        try:
            source.unlink()
        except BaseException:
            target.unlink(missing_ok=True)
            info.unlink(missing_ok=True)
            raise
        return target
    raise AssertionError("unreachable")  # pragma: no cover - count() é infinito


def _candidate_names(name: str):
    yield name
    path = Path(name)
    for sequence in count(2):
        yield f"{path.stem}.{sequence}{path.suffix}"
