"""Android: what a game's app is built with, fetched once into the cache folder.

- **The Android SDK** (``android_sdk``): Google's command-line tools, then the platform,
  build tools, NDK and CMake that the app needs, installed with their ``sdkmanager``.
  Installing them accepts Google's Android SDK licence, which gbaport says when it does.
- **Gradle** (``gradle``), which builds the app; it runs on a JDK 17 or newer
  (``java_environment``).
- **SDL3's source** (``sdl3_source``): the app builds SDL3 from it and takes SDL's Java
  code for its activity.

Each download is checked against the digest its publisher lists and unpacked under a
name of its own first, so an interrupted one leaves nothing that looks installed.
"""

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from gbaport.native.sdl3 import SDL3_SHA256, SDL3_URL, SDL3_VERSION, cache_folder
from gbaport.native.toolchain import ToolchainError

GRADLE_VERSION = "8.12.1"  # with the Android Gradle plugin 8.7.3, as SDL3's android-project
GRADLE_URL = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
GRADLE_SHA256 = "8d97a97984f6cbd2b85fe4c60a743440a347544bf18818048e611f5288d46c94"
PLATFORM = 35
BUILD_TOOLS = "35.0.0"
NDK = "29.0.14206865"  # r29
CMAKE = "3.31.6"
SDK_PACKAGES = (
    "platform-tools", f"platforms;android-{PLATFORM}", f"build-tools;{BUILD_TOOLS}",
    f"ndk;{NDK}", f"cmake;{CMAKE}",
)
REPOSITORY = "https://dl.google.com/android/repository/"
COMMAND_LINE_TOOLS = {  # version 23.0: archive and SHA-1, as Google's repository lists them
    "win32": ("commandlinetools-win-16111833_latest.zip", "57d04f2d75eb8e8fffc5000a987e5de4b5a63e9d"),
    "linux": ("commandlinetools-linux-16111833_latest.zip", "e025545c62a8e64c7559119566a569fb1dec5f60"),
    "darwin": ("commandlinetools-mac_arm64-16111833_latest.zip", "ad03dc49bfacfd52c110b14104ea548b8a07e830"),
}
LICENCE = "https://developer.android.com/studio/terms"

Log = Callable[[str], None]


def android_sdk(log: Log = print) -> Path:
    """The SDK folder, with the packages gbaport needs (installed the first time)."""
    sdk = cache_folder() / "android-sdk"
    if not _sdkmanager(sdk).exists():
        name, sha1 = COMMAND_LINE_TOOLS[sys.platform]
        log(f"downloading Google's Android command-line tools into {sdk}")
        archive = _download(REPOSITORY + name, sdk / name, sha1, "sha1")
        _unpack(archive, "cmdline-tools", sdk / "cmdline-tools" / "latest")
    missing = [p for p in SDK_PACKAGES if not installed(sdk, p)]
    if missing:
        install_packages(sdk, missing, log)
    return sdk


def installed(sdk: Path, package: str) -> bool:
    return (sdk.joinpath(*package.split(";")) / "source.properties").exists()


def install_packages(sdk: Path, packages: list[str], log: Log = print) -> None:
    """Installs ``packages`` with the SDK's sdkmanager, saying yes to their licences."""
    log(f"installing {', '.join(packages)} into {sdk}; this accepts Google's Android SDK "
        f"licence ({LICENCE})")
    listing = sdk / "packages.txt"  # a .bat file's arguments cannot hold the ';' in the names
    listing.write_text("\n".join(packages) + "\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [str(_sdkmanager(sdk)), f"--sdk_root={sdk}", f"--package_file={listing}"],
            input="y\n" * 50, capture_output=True, text=True, env=java_environment(), check=False,
        )
    finally:
        listing.unlink()
    missing = [p for p in packages if not installed(sdk, p)]
    if result.returncode != 0 or missing:
        raise ToolchainError(f"installing {', '.join(missing or packages)} failed:\n"
                             f"{(result.stdout + result.stderr)[-4000:]}")


def _sdkmanager(sdk: Path) -> Path:
    name = "sdkmanager.bat" if os.name == "nt" else "sdkmanager"
    return sdk / "cmdline-tools" / "latest" / "bin" / name


def java_environment() -> dict[str, str]:
    """The environment with JAVA_HOME set, which Gradle and the SDK's tools need."""
    env = dict(os.environ)
    if not env.get("JAVA_HOME"):
        java = shutil.which("java")
        if not java:
            raise ToolchainError("Java not found: Gradle and the Android SDK need a JDK 17 or "
                                 "newer (winget install EclipseAdoptium.Temurin.17.JDK)")
        env["JAVA_HOME"] = str(Path(java).resolve().parent.parent)
    return env


def gradle(log: Log = print) -> Path:
    """Gradle's launcher (downloaded the first time)."""
    home = cache_folder() / f"gradle-{GRADLE_VERSION}"
    program = home / "bin" / ("gradle.bat" if os.name == "nt" else "gradle")
    if not program.exists():
        log(f"downloading Gradle {GRADLE_VERSION} into {home}")
        archive = _download(GRADLE_URL, cache_folder() / f"gradle-{GRADLE_VERSION}-bin.zip",
                            GRADLE_SHA256)
        _unpack(archive, f"gradle-{GRADLE_VERSION}", home)
    return program


def sdl3_source(log: Log = print) -> Path:
    """SDL3's source release (downloaded the first time)."""
    folder = cache_folder() / f"sdl3-{SDL3_VERSION}-source"
    if not (folder / "CMakeLists.txt").exists():
        log(f"downloading SDL3 {SDL3_VERSION}'s source into {folder}")
        archive = _download(SDL3_URL, cache_folder() / f"SDL3-{SDL3_VERSION}.tar.gz", SDL3_SHA256)
        _unpack(archive, f"SDL3-{SDL3_VERSION}", folder)
    return folder


def _download(url: str, path: Path, digest: str, kind: str = "sha256") -> Path:
    """``url`` saved as ``path``, if its bytes have the published ``digest``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    hasher = hashlib.new(kind)
    try:
        with urllib.request.urlopen(url) as response, open(partial, "wb") as out:
            while chunk := response.read(1 << 20):
                hasher.update(chunk)
                out.write(chunk)
    except OSError as error:
        partial.unlink(missing_ok=True)
        raise ToolchainError(f"cannot download {url}: {error}") from error
    if hasher.hexdigest() != digest:
        partial.unlink()
        raise ToolchainError(f"{url} did not download as published ({kind} {hasher.hexdigest()})")
    partial.replace(path)
    return path


def _unpack(archive: Path, top: str, target: Path) -> None:
    """Unpacks ``archive``'s folder ``top`` as ``target``, then deletes the archive."""
    staging = target.with_name(target.name + "-unpacking")
    shutil.rmtree(staging, ignore_errors=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(staging)
            for info in zipped.infolist():  # zipfile drops the permissions: keep +x
                if info.external_attr >> 16 and os.name != "nt":
                    (staging / info.filename).chmod(info.external_attr >> 16)
    else:
        with tarfile.open(archive) as packed:
            packed.extractall(staging, filter="data")
    shutil.rmtree(target, ignore_errors=True)
    (staging / top).replace(target)
    shutil.rmtree(staging, ignore_errors=True)
    archive.unlink()
