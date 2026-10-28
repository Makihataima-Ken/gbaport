"""Android: a game's app, a Gradle project built with the Android SDK and NDK.

``android_project`` writes the project from ``android_template``: the game's generated C
sources, the runtime and its window host (``host_sdl.c``, which knows phones), SDL3's
Java code and the ROM, as an asset. ``build_apk`` builds it with Gradle into an APK signed
with the SDK's debug key, which phones install over USB. What they need comes into the
cache folder the first time:

- **The Android SDK** (``android_sdk``): Google's command-line tools, then the platform,
  build tools, NDK and CMake that the app needs, installed with their ``sdkmanager``.
  Installing them accepts Google's Android SDK licence, which gbaport says when it does.
- **Gradle** (``gradle``), which builds the app; it runs on a JDK 17 or newer
  (``java_environment``). Its downloads (the Android Gradle plugin) go to ``gradle-home``.
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

from gbaport.native.build import CFLAGS, RUNTIME, RUNTIME_SOURCES
from gbaport.native.sdl3 import SDL3_SHA256, SDL3_URL, SDL3_VERSION, cache_folder
from gbaport.native.toolchain import ToolchainError

TEMPLATE = Path(__file__).parent / "android_template"
ANDROID_PLUGIN = "8.7.3"
HOST_SOURCES = ("host_common.c", "host_sdl.c", "touch.c")
ABIS = ("arm64-v8a", "x86_64")  # phones; the emulator on a PC
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


def application_id(game_code: str) -> str:
    """The app's name on the phone: org.gbaport.<game code>, so each game is its own app."""
    code = "".join(c for c in game_code.lower() if c.isascii() and c.isalnum())
    return f"org.gbaport.{'g' + code if code[:1].isdigit() else code or 'game'}"


def android_project(sources: Path, rom: bytes, out: Path, game_code: str, label: str,
                    abis: tuple[str, ...], sdl: Path, sdk: Path) -> Path:
    """Writes the app's Gradle project to ``out``: the game's C ``sources`` (gbaport
    recompile's folder), the runtime, SDL3's Java code from ``sdl`` and the ``rom``, built
    for ``abis`` with the SDK in ``sdk``. Writing it again replaces what an earlier run
    wrote, and keeps Gradle's and CMake's build folders, so a rebuild compiles only what
    changed."""
    main = out / "app" / "src" / "main"
    cpp = main / "cpp"
    for folder in (cpp / "generated", cpp / "runtime", main / "java", main / "assets", main / "res"):
        shutil.rmtree(folder, ignore_errors=True)
    shutil.copytree(sources, cpp / "generated")
    (cpp / "runtime").mkdir(parents=True)
    for path in RUNTIME.glob("*.[ch]"):
        shutil.copy2(path, cpp / "runtime" / path.name)
    sdl_main = sdl / "android-project" / "app" / "src" / "main"
    shutil.copytree(sdl_main / "java", main / "java")
    for icons in (sdl_main / "res").glob("mipmap-*"):
        shutil.copytree(icons, main / "res" / icons.name)
    (main / "assets").mkdir(parents=True)
    (main / "assets" / "game.gba").write_bytes(rom)
    units = [f"generated/{path.name}" for path in sorted((cpp / "generated").glob("*.c"))]
    units += [f"runtime/{name}" for name in (*RUNTIME_SOURCES, *HOST_SOURCES)]
    name = "".join(c for c in game_code if c.isascii() and c.isalnum()) or "game"
    values = {
        "NAME": name, "LABEL": _resource_string(label or game_code or "gbaport"),
        "ANDROID_PLUGIN": ANDROID_PLUGIN, "PLATFORM": str(PLATFORM), "BUILD_TOOLS": BUILD_TOOLS,
        "NDK": NDK, "CMAKE": CMAKE, "APPLICATION_ID": application_id(game_code),
        "ABIS": ", ".join(f"'{abi}'" for abi in abis), "SDL3_SOURCE": sdl.as_posix(),
        "SOURCES": "\n".join(f"    {unit}" for unit in units), "CFLAGS": " ".join(CFLAGS),
    }
    for template in TEMPLATE.rglob("*"):
        if template.is_file():
            text = template.read_text(encoding="utf-8")
            for key, value in values.items():
                text = text.replace(f"@{key}@", value)
            target = out / template.relative_to(TEMPLATE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    escaped = str(sdk).replace("\\", "\\\\").replace(":", "\\:")  # a Java properties file
    (out / "local.properties").write_text(f"sdk.dir={escaped}\n", encoding="utf-8")
    return out


def _resource_string(text: str) -> str:
    """``text`` as an Android string resource: XML's escapes, then Android's (backslash,
    quotes, a leading @ or ?), without control characters."""
    text = "".join(c for c in text if c.isprintable())
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")
    return "\\" + text if text[:1] in ("@", "?") else text


def build_apk(project: Path, apk: Path, log: Log = print) -> Path:
    """Builds ``project`` (android_project's) with Gradle; the APK is copied to ``apk``."""
    env = {**java_environment(), "ANDROID_HOME": str(android_sdk(log)),
           "GRADLE_USER_HOME": str(cache_folder() / "gradle-home")}
    result = subprocess.run(
        [str(gradle(log)), "--no-daemon", "--console=plain", "-p", str(project), "assembleDebug"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False,
    )
    if result.returncode != 0:
        raise ToolchainError(f"Gradle failed to build {project}:\n"
                             f"{(result.stdout + result.stderr)[-6000:]}")
    apk.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(project / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk", apk)
    return apk
