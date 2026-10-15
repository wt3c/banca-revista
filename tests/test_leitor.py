from __future__ import annotations

import hashlib
import io
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from banca_revista.leitor import (
    PANELSPLUS,
    InstallError,
    PluginRelease,
    flatpak_commands,
    install_reader,
    koreader_config_dir,
)

ORIGINAL_MAIN = 'local name = "panelsplus"\nreturn name\n'
PATCHED_MAIN = 'local name = "panelsplus"\nlocal double_tap = true\nreturn name\n'


def make_zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def make_patch(tmp_path: Path) -> Path:
    """Gera um patch real com `diff -u`, no mesmo formato do patch empacotado."""
    work = tmp_path / "patch-src"
    (work / "a").mkdir(parents=True)
    (work / "b").mkdir()
    (work / "a" / "main.lua").write_text(ORIGINAL_MAIN)
    (work / "b" / "main.lua").write_text(PATCHED_MAIN)
    result = subprocess.run(
        ["diff", "-u", "a/main.lua", "b/main.lua"], cwd=work, capture_output=True, text=True, check=False
    )
    assert result.returncode == 1, result.stderr
    patch = tmp_path / "plugin.patch"
    patch.write_text(result.stdout)
    return patch


class FakeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, command: list[str]) -> int:
        self.calls.append(command)
        return self.returncode


class FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        return self.data


@pytest.fixture
def plugin_zip() -> bytes:
    return make_zip({"panelsplus.koplugin/main.lua": ORIGINAL_MAIN, "panelsplus.koplugin/_meta.lua": "return {}\n"})


@pytest.fixture
def release(tmp_path: Path, plugin_zip: bytes) -> PluginRelease:
    return PluginRelease(
        url="https://example.invalid/panels_plus.koplugin.zip",
        sha256=hashlib.sha256(plugin_zip).hexdigest(),
        folder="panelsplus.koplugin",
        patch=make_patch(tmp_path),
    )


def plugins_dir(home: Path) -> Path:
    return koreader_config_dir(home) / "plugins"


def test_koreader_config_dir_is_the_flatpak_sandbox_config(tmp_path: Path) -> None:
    assert koreader_config_dir(tmp_path) == tmp_path / ".var/app/rocks.koreader.KOReader/config/koreader"


def test_flatpak_commands_add_flathub_and_install_for_the_user() -> None:
    assert flatpak_commands() == [
        [
            "flatpak",
            "remote-add",
            "--user",
            "--if-not-exists",
            "flathub",
            "https://dl.flathub.org/repo/flathub.flatpakrepo",
        ],
        ["flatpak", "install", "--user", "--or-update", "--noninteractive", "-y", "flathub", "rocks.koreader.KOReader"],
    ]


def test_simulation_changes_nothing(tmp_path: Path, release: PluginRelease, plugin_zip: bytes) -> None:
    home = tmp_path / "home"
    runner, downloader = FakeRunner(), FakeDownloader(plugin_zip)

    steps = install_reader(home, simulate=True, release=release, runner=runner, downloader=downloader)

    assert steps
    assert runner.calls == []
    assert downloader.urls == []
    assert not home.exists()


def test_installs_app_and_patched_plugin(tmp_path: Path, release: PluginRelease, plugin_zip: bytes) -> None:
    home = tmp_path / "home"
    runner, downloader = FakeRunner(), FakeDownloader(plugin_zip)

    install_reader(home, release=release, runner=runner, downloader=downloader)

    assert runner.calls == flatpak_commands()
    assert downloader.urls == [release.url]
    plugin = plugins_dir(home) / "panelsplus.koplugin"
    assert (plugin / "main.lua").read_text() == PATCHED_MAIN
    assert (plugin / "_meta.lua").exists()
    assert sorted(p.name for p in plugins_dir(home).iterdir()) == ["panelsplus.koplugin"]
    assert not list(plugin.rglob("*.orig"))
    assert [p.name for p in koreader_config_dir(home).iterdir() if p.name.startswith(".")] == []


def test_existing_plugin_is_backed_up_outside_plugins_dir(
    tmp_path: Path, release: PluginRelease, plugin_zip: bytes
) -> None:
    home = tmp_path / "home"
    old = plugins_dir(home) / "panelsplus.koplugin"
    old.mkdir(parents=True)
    (old / "main.lua").write_text("old\n")

    install_reader(home, release=release, runner=FakeRunner(), downloader=FakeDownloader(plugin_zip))

    assert (old / "main.lua").read_text() == PATCHED_MAIN
    backups = list((koreader_config_dir(home) / "plugins.bak").iterdir())
    assert len(backups) == 1
    assert backups[0].name.startswith("panelsplus.koplugin-")
    assert (backups[0] / "main.lua").read_text() == "old\n"
    assert sorted(p.name for p in plugins_dir(home).iterdir()) == ["panelsplus.koplugin"]


def test_checksum_mismatch_keeps_existing_plugin(tmp_path: Path, release: PluginRelease) -> None:
    home = tmp_path / "home"
    old = plugins_dir(home) / "panelsplus.koplugin"
    old.mkdir(parents=True)
    (old / "main.lua").write_text("old\n")
    tampered = make_zip({"panelsplus.koplugin/main.lua": "malicious\n"})

    with pytest.raises(InstallError, match="SHA-256"):
        install_reader(home, release=release, runner=FakeRunner(), downloader=FakeDownloader(tampered))

    assert (old / "main.lua").read_text() == "old\n"
    assert not (koreader_config_dir(home) / "plugins.bak").exists()


@pytest.mark.parametrize("member", ["../evil.lua", "/abs/evil.lua", "panelsplus.koplugin/../../evil.lua"])
def test_rejects_unsafe_zip_members(tmp_path: Path, member: str) -> None:
    data = make_zip({"panelsplus.koplugin/main.lua": ORIGINAL_MAIN, member: "x"})
    release = PluginRelease(
        url="https://example.invalid/p.zip",
        sha256=hashlib.sha256(data).hexdigest(),
        folder="panelsplus.koplugin",
        patch=make_patch(tmp_path),
    )
    home = tmp_path / "home"

    with pytest.raises(InstallError, match="insegura"):
        install_reader(home, release=release, runner=FakeRunner(), downloader=FakeDownloader(data))

    assert not (tmp_path / "evil.lua").exists()
    assert not (plugins_dir(home) / "panelsplus.koplugin").exists()


def test_patch_that_does_not_apply_keeps_existing_plugin(tmp_path: Path, release: PluginRelease) -> None:
    home = tmp_path / "home"
    old = plugins_dir(home) / "panelsplus.koplugin"
    old.mkdir(parents=True)
    (old / "main.lua").write_text("old\n")
    other = make_zip({"panelsplus.koplugin/main.lua": "outra versão\n"})
    release = PluginRelease(release.url, hashlib.sha256(other).hexdigest(), release.folder, release.patch)

    with pytest.raises(InstallError, match="patch"):
        install_reader(home, release=release, runner=FakeRunner(), downloader=FakeDownloader(other))

    assert (old / "main.lua").read_text() == "old\n"
    assert [p.name for p in koreader_config_dir(home).iterdir() if p.name.startswith(".")] == []


def test_flatpak_failure_stops_before_touching_plugin(
    tmp_path: Path, release: PluginRelease, plugin_zip: bytes
) -> None:
    home = tmp_path / "home"
    downloader = FakeDownloader(plugin_zip)

    with pytest.raises(InstallError, match="flatpak"):
        install_reader(home, release=release, runner=FakeRunner(returncode=1), downloader=downloader)

    assert downloader.urls == []
    assert not plugins_dir(home).exists()


def test_bundled_patch_file_is_packaged() -> None:
    assert PANELSPLUS.patch.is_file()
    assert "registerDoubleTapPanelZoom" in PANELSPLUS.patch.read_text()


@pytest.mark.skipif(not os.environ.get("BANCA_TESTE_REDE"), reason="defina BANCA_TESTE_REDE=1 para baixar do GitHub")
def test_real_release_download_and_bundled_patch(tmp_path: Path) -> None:
    home = tmp_path / "home"

    install_reader(home, runner=FakeRunner())

    plugin = plugins_dir(home) / "panelsplus.koplugin"
    assert 'mode = "comic"' in (plugin / "src/_settings.lua").read_text()
    assert "getFixedZoomShrinkFactor" in (plugin / "src/_panelviewer.lua").read_text()
    assert "registerDoubleTapPanelZoom" in (plugin / "main.lua").read_text()


def test_cli_simulation_prints_plan_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from banca_revista import cli

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("sys.argv", ["banca-revista", "instalar-leitor", "--simular"])

    assert cli.main() == 0

    out = capsys.readouterr().out
    assert "simulação" in out
    assert "flatpak install --user" in out
    assert not home.exists()
