"""Instalação do leitor KOReader (Flatpak) com o plugin Panels+ adaptado.

O Panels+ v1.4.0 é baixado do release oficial, conferido por SHA-256 e recebe o
patch empacotado em ``dados/`` (duplo clique abre o quadro, zoom fixo entre
quadros e leitura da esquerda para a direita por padrão).
"""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

KOREADER_APP_ID = "rocks.koreader.KOReader"
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"
DOWNLOAD_TIMEOUT_SECONDS = 60


class InstallError(RuntimeError):
    """Falha que interrompe a instalação sem alterar o plugin já instalado."""


class CommandRunner(Protocol):
    def __call__(self, command: list[str]) -> int: ...


class Downloader(Protocol):
    def __call__(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class PluginRelease:
    url: str
    sha256: str
    folder: str
    patch: Path


PANELSPLUS = PluginRelease(
    url="https://github.com/KristanLaimon/PanelsPlus/releases/download/v1.4.0/panels_plus.koplugin.zip",
    sha256="a0b40f1028712d9cd3b7c97e15fa2eaaf77f312caebc2fb7d896f156757cf26c",
    folder="panelsplus.koplugin",
    patch=Path(__file__).parent / "dados" / "panelsplus-v1.4.0.patch",
)


def koreader_config_dir(home: Path) -> Path:
    return home / ".var" / "app" / KOREADER_APP_ID / "config" / "koreader"


def flatpak_commands() -> list[list[str]]:
    return [
        ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_URL],
        ["flatpak", "install", "--user", "--or-update", "--noninteractive", "-y", "flathub", KOREADER_APP_ID],
    ]


def run_command(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        return response.read()


def install_reader(
    home: Path,
    *,
    simulate: bool = False,
    release: PluginRelease = PANELSPLUS,
    runner: CommandRunner = run_command,
    downloader: Downloader = download,
    report: Callable[[str], None] = lambda _line: None,
) -> list[str]:
    """Instala o KOReader e o plugin; devolve as etapas executadas (ou planejadas)."""
    plugins = koreader_config_dir(home) / "plugins"
    target = plugins / release.folder
    steps = [" ".join(command) for command in flatpak_commands()]
    steps.append(f"baixar {release.url} e conferir SHA-256 {release.sha256}")
    steps.append(f"aplicar {release.patch.name}")
    if target.exists():
        steps.append(f"mover o plugin atual para {koreader_config_dir(home) / 'plugins.bak'}")
    steps.append(f"instalar o plugin em {target}")
    if simulate:
        return steps

    for command in flatpak_commands():
        report(" ".join(command))
        if runner(command) != 0:
            raise InstallError(f"comando flatpak falhou: {' '.join(command)}")

    report(f"baixando {release.url}")
    data = downloader(release.url)
    digest = hashlib.sha256(data).hexdigest()
    if digest != release.sha256:
        raise InstallError(f"SHA-256 inesperado: {digest} (esperado {release.sha256})")

    plugins.mkdir(parents=True, exist_ok=True)
    # Montado fora de plugins/ para o KOReader nunca carregar uma cópia incompleta,
    # mas no mesmo sistema de arquivos para a troca final ser um rename.
    with tempfile.TemporaryDirectory(prefix=".banca-revista-", dir=plugins.parent) as staging:
        staged = _extract_plugin(data, Path(staging), release.folder)
        report(f"aplicando {release.patch.name}")
        _apply_patch(staged, release.patch)
        backup = _replace_dir(staged, target, koreader_config_dir(home) / "plugins.bak")
        if backup:
            report(f"plugin anterior guardado em {backup}")
    report(f"plugin instalado em {target}")
    return steps


def _extract_plugin(data: bytes, staging: Path, folder: str) -> Path:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or not parts or parts[0] != folder:
                raise InstallError(f"entrada insegura ou inesperada no zip: {name}")
        archive.extractall(staging)
    plugin = staging / folder
    if not plugin.is_dir():
        raise InstallError(f"o zip não contém a pasta {folder}")
    return plugin


def _apply_patch(plugin: Path, patch: Path) -> None:
    if shutil.which("patch") is None:
        raise InstallError("o comando patch não está instalado")
    result = subprocess.run(
        # --fuzz=0: um patch só aplica sobre o conteúdo exato do release, nunca "por aproximação".
        [
            "patch",
            "-p1",
            "--batch",
            "--forward",
            "--fuzz=0",
            "--no-backup-if-mismatch",
            "-d",
            str(plugin),
            "-i",
            str(patch),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise InstallError(f"o patch não aplicou:\n{result.stdout}{result.stderr}")


def _replace_dir(new: Path, target: Path, backups: Path) -> Path | None:
    backup = None
    if target.exists():
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"{target.name}-{datetime.now():%Y%m%d-%H%M%S-%f}"
        target.rename(backup)
    new.rename(target)
    return backup
