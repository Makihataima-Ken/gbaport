"""What a game's Android app is built with (gbaport/native/android.py), without Google's
servers: a stand-in sdkmanager and local files for the downloads."""

import hashlib
import io
import os
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

import pytest

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
            if "broken" not in package:
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
    with pytest.raises(ToolchainError, match=r"installing broken;1 failed"):
        android.android_sdk(log=quiet)


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
