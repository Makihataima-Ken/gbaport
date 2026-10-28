"""A game's Android app (gbaport/native/android.py): what it is built with, tested with a
stand-in sdkmanager and local files for the downloads; its Gradle project, with a
stand-in SDL3; and one real build, of a test ROM's app."""

import hashlib
import io
import os
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest
from androidkit import rom_apk
from romtest import build_test_rom

from gbaport.native import android
from gbaport.native.toolchain import ToolchainError

FAKE_SDKMANAGER = textwrap.dedent("""\
    import sys
    from pathlib import Path
    args = dict(a.split("=", 1) for a in sys.argv[1:])
    sdk = Path(args["--sdk_root"])
    answers = sys.stdin.read().split()
    with open(sdk / "calls.txt", "a", encoding="utf-8") as calls:
        calls.write(f"{len(answers)} answers:")
        for package in Path(args["--package_file"]).read_text(encoding="utf-8").split():
            calls.write(" " + package)
            if "broken" in package:  # says why in bytes that are not text in any code page
                sys.stdout.buffer.write(b"\\x81\\x8d cannot install " + package.encode() + b"\\n")
            else:
                folder = sdk.joinpath(*package.split(";"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "source.properties").write_text("Pkg.Revision=1\\n", encoding="utf-8")
        calls.write("\\n")
""")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("GBAPORT_CACHE", str(tmp_path / "cache"))
    return tmp_path / "cache"


def fake_sdk(cache: Path) -> Path:
    """An SDK folder whose sdkmanager installs whatever it is asked for, at once."""
    tools = cache / "android-sdk" / "cmdline-tools" / "latest" / "bin"
    tools.mkdir(parents=True)
    script = tools / "fake_sdkmanager.py"
    script.write_text(FAKE_SDKMANAGER, encoding="utf-8")
    if os.name == "nt":
        (tools / "sdkmanager.bat").write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        launcher = tools / "sdkmanager"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return cache / "android-sdk"


def quiet(_: str) -> None:
    pass


def test_the_sdk_packages_gbaport_needs_are_installed_once(cache):
    sdk = fake_sdk(cache)
    assert android.android_sdk(log=quiet) == sdk
    android.android_sdk(log=quiet)  # all there now: sdkmanager does not run again
    calls = (sdk / "calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls == ["50 answers: " + " ".join(android.SDK_PACKAGES)]  # "y" to every licence
    assert (sdk / "ndk" / android.NDK / "source.properties").exists()
    assert not (sdk / "packages.txt").exists()


def test_installing_says_it_accepts_googles_licence(cache):
    fake_sdk(cache)
    said = []
    android.android_sdk(log=said.append)
    assert len(said) == 1 and "accepts Google's Android SDK licence" in said[0]


def test_a_package_that_does_not_install_is_named(cache, monkeypatch):
    fake_sdk(cache)
    monkeypatch.setattr(android, "SDK_PACKAGES", ("platform-tools", "broken;1"))
    with pytest.raises(ToolchainError, match=r"installing broken;1 failed[\s\S]*cannot install broken;1"):
        android.android_sdk(log=quiet)  # its words, whatever bytes they come in


def test_a_download_must_match_its_published_digest(tmp_path):
    source = tmp_path / "file.zip"
    source.write_bytes(b"published bytes")
    digest = hashlib.sha256(b"published bytes").hexdigest()
    target = tmp_path / "downloads" / "file.zip"
    assert android._download(source.as_uri(), target, digest) == target
    assert target.read_bytes() == b"published bytes"
    with pytest.raises(ToolchainError, match="did not download as published"):
        android._download(source.as_uri(), tmp_path / "other.zip", "0" * 64)
    assert not (tmp_path / "other.zip").exists()
    assert not (tmp_path / "other.zip.partial").exists()


def test_a_download_that_fails_says_what_it_was(tmp_path):
    with pytest.raises(ToolchainError, match="cannot download"):
        android._download((tmp_path / "nothing.zip").as_uri(), tmp_path / "x.zip", "0" * 64)
    assert not (tmp_path / "x.zip.partial").exists()


def test_a_download_gives_up_on_a_server_that_stops_answering(tmp_path, monkeypatch):
    asked = {}

    def stalls(url, timeout=None):
        asked["timeout"] = timeout
        raise TimeoutError("timed out")

    monkeypatch.setattr(android.urllib.request, "urlopen", stalls)
    with pytest.raises(ToolchainError, match="cannot download .*timed out"):
        android._download("https://dl.google.com/x.zip", tmp_path / "x.zip", "0" * 64)
    assert asked["timeout"] == android.DOWNLOAD_TIMEOUT  # a stalled server ends it, not hangs it


def test_gradle_and_sdl3s_source_come_unpacked_into_the_cache(cache, monkeypatch, tmp_path):
    gradle_zip = io.BytesIO()
    with zipfile.ZipFile(gradle_zip, "w") as zipped:
        zipped.writestr(f"gradle-{android.GRADLE_VERSION}/bin/gradle", "#!/bin/sh\n")
        zipped.writestr(f"gradle-{android.GRADLE_VERSION}/bin/gradle.bat", "@echo off\n")
    sdl_tar = io.BytesIO()
    with tarfile.open(fileobj=sdl_tar, mode="w:gz") as packed:
        data = b"project(SDL3)\n"
        info = tarfile.TarInfo(f"SDL3-{android.SDL3_VERSION}/CMakeLists.txt")
        info.size = len(data)
        packed.addfile(info, io.BytesIO(data))
    published = {}
    for name, blob in (("gradle.zip", gradle_zip.getvalue()), ("sdl.tar.gz", sdl_tar.getvalue())):
        (tmp_path / name).write_bytes(blob)
        published[name] = ((tmp_path / name).as_uri(), hashlib.sha256(blob).hexdigest())
    monkeypatch.setattr(android, "GRADLE_URL", published["gradle.zip"][0])
    monkeypatch.setattr(android, "GRADLE_SHA256", published["gradle.zip"][1])
    monkeypatch.setattr(android, "SDL3_URL", published["sdl.tar.gz"][0])
    monkeypatch.setattr(android, "SDL3_SHA256", published["sdl.tar.gz"][1])
    program = android.gradle(log=quiet)
    assert program.parent == cache / f"gradle-{android.GRADLE_VERSION}" / "bin" and program.exists()
    source = android.sdl3_source(log=quiet)
    assert (source / "CMakeLists.txt").read_text(encoding="utf-8") == "project(SDL3)\n"
    assert sorted(p.name for p in cache.iterdir()) == [
        f"gradle-{android.GRADLE_VERSION}", f"sdl3-{android.SDL3_VERSION}-source"]  # no archives left


@pytest.mark.parametrize("code, expected", [
    ("BT4E", "org.gbaport.bt4e"), ("ATST", "org.gbaport.atst"), ("1ABC", "org.gbaport.g1abc"),
    ("", "org.gbaport.game"), ("A-Bé", "org.gbaport.ab"),
])
def test_each_game_is_an_app_of_its_own(code, expected):
    assert android.application_id(code) == expected


def fake_sdl(tmp_path: Path) -> Path:
    sdl = tmp_path / "sdl"
    main = sdl / "android-project" / "app" / "src" / "main"
    (main / "java" / "org" / "libsdl" / "app").mkdir(parents=True)
    (main / "java" / "org" / "libsdl" / "app" / "SDLActivity.java").write_text(
        "package org.libsdl.app;\n", encoding="utf-8")
    for density in ("mdpi", "hdpi"):
        (main / "res" / f"mipmap-{density}").mkdir(parents=True)
        (main / "res" / f"mipmap-{density}" / "ic_launcher.png").write_bytes(b"png")
    return sdl


def generated(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "generated"
    folder.mkdir(exist_ok=True)
    for name in (*names, "gba_cpu.h"):
        (folder / name).write_text(f"/* {name} */\n", encoding="utf-8")
    return folder


def test_the_project_holds_the_game_the_runtime_sdl_and_the_rom(tmp_path):
    sdk = tmp_path / "an sdk"
    sources = generated(tmp_path, "gba_code_000.c", "gba_dispatch.c")
    out = android.android_project(sources, b"rom bytes", tmp_path / "project", "BT4E", "DBZ & GT",
                                  ("arm64-v8a", "x86_64"), fake_sdl(tmp_path), sdk)
    main = out / "app" / "src" / "main"
    assert (main / "assets" / "game.gba").read_bytes() == b"rom bytes"
    assert (main / "java" / "org" / "libsdl" / "app" / "SDLActivity.java").exists()
    assert (main / "java" / "org" / "gbaport" / "game" / "GameActivity.java").exists()
    assert (main / "res" / "mipmap-hdpi" / "ic_launcher.png").exists()
    assert (main / "cpp" / "generated" / "gba_cpu.h").exists()
    assert (main / "cpp" / "runtime" / "touch.h").exists()
    cmake = (main / "cpp" / "CMakeLists.txt").read_text(encoding="utf-8")
    units = [line.strip() for line in cmake.splitlines() if line.strip().endswith(".c")]
    assert units == ["generated/gba_code_000.c", "generated/gba_dispatch.c",
                     *(f"runtime/{n}" for n in (*android.RUNTIME_SOURCES, *android.HOST_SOURCES))]
    assert f'add_subdirectory("{(tmp_path / "sdl").as_posix()}" SDL3)' in cmake
    gradle = (out / "app" / "build.gradle").read_text(encoding="utf-8")
    assert 'applicationId = "org.gbaport.bt4e"' in gradle
    assert "abiFilters 'arm64-v8a', 'x86_64'" in gradle
    assert f'ndkVersion = "{android.NDK}"' in gradle
    assert "DBZ &amp; GT" in (main / "res" / "values" / "strings.xml").read_text(encoding="utf-8")
    written = [p.read_text(encoding="utf-8") for p in out.rglob("*") if p.suffix in
               {".gradle", ".txt", ".xml", ".java", ".properties"}]
    assert not any("@" + key in text for text in written for key in ("NAME", "NDK", "SOURCES"))
    escaped = str(sdk).replace("\\", "\\\\").replace(":", "\\:")
    assert (out / "local.properties").read_text(encoding="utf-8") == f"sdk.dir={escaped}\n"


def test_writing_the_project_again_replaces_what_the_game_left(tmp_path):
    sdl = fake_sdl(tmp_path)
    sources = generated(tmp_path, "gba_code_000.c", "gba_code_001.c")
    out = android.android_project(sources, b"1", tmp_path / "project", "ATST", "", ("x86_64",),
                                  sdl, tmp_path / "sdk")
    (out / "app" / "build").mkdir()  # Gradle's: kept, so that a rebuild compiles less
    (sources / "gba_code_001.c").unlink()
    android.android_project(sources, b"2", out, "ATST", "", ("x86_64",), sdl, tmp_path / "sdk")
    cpp = out / "app" / "src" / "main" / "cpp"
    assert not (cpp / "generated" / "gba_code_001.c").exists()
    assert "gba_code_001" not in (cpp / "CMakeLists.txt").read_text(encoding="utf-8")
    assert (out / "app" / "src" / "main" / "assets" / "game.gba").read_bytes() == b"2"
    assert (out / "app" / "build").is_dir()


def test_a_test_roms_app_holds_its_code_for_the_emulator_and_its_rom():
    """A real build with Gradle (the first one fetches the Android Gradle plugin and
    compiles SDL3, which takes some minutes)."""
    apk = rom_apk("hello")
    with zipfile.ZipFile(apk) as zipped:
        names = set(zipped.namelist())
        assert {"lib/x86_64/libmain.so", "lib/x86_64/libSDL3.so", "assets/game.gba"} <= names
        assert zipped.read("assets/game.gba") == build_test_rom("hello").data
        assert zipped.getinfo("assets/game.gba").compress_type == zipfile.ZIP_STORED
        dex = b"".join(zipped.read(name) for name in names if name.endswith(".dex"))
    assert b"Lorg/gbaport/game/GameActivity;" in dex


def test_odd_titles_and_game_codes_go_into_the_project_safely(tmp_path):
    out = android.android_project(generated(tmp_path, "gba_code_08000000.c"), b"1", tmp_path / "p",
                                  'A"\\B', '@Mo\\ "Best"\x01?', ("x86_64",), fake_sdl(tmp_path),
                                  tmp_path / "sdk")
    assert 'rootProject.name = "AB"' in (out / "settings.gradle").read_text(encoding="utf-8")
    strings = out / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    assert '<string name="app_name">\\@Mo\\\\ \\"Best\\"?</string>' in \
        strings.read_text(encoding="utf-8")
