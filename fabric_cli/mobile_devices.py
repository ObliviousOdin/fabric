"""Attached-device discovery and debug installation for ``fabric mobile``.

This module deliberately contains no gateway or authentication logic. It only
runs native build/install tooling from a source checkout, with argv-based
subprocesses and without ever accepting or logging pairing credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


ANDROID_BUNDLE_ID = "io.github.obliviousodin.fabric.mobile"
IOS_BUNDLE_ID = "io.github.obliviousodin.fabric.mobile"


def _is_windows() -> bool:
    return os.name == "nt"


class MobileInstallError(RuntimeError):
    """A requested native install could not be completed safely."""


@dataclass(frozen=True)
class MobileDevice:
    platform: str
    identifier: str
    name: str
    state: str = "connected"

    @property
    def label(self) -> str:
        return f"{self.name} ({self.identifier})"


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except OSError as exc:
        raise MobileInstallError(f"Could not run {Path(argv[0]).name}: {exc}") from exc


def _find_adb() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb",
        Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb",
        Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
        Path.home() / "Android" / "Sdk" / "platform-tools" / "adb",
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def _java_environment() -> dict[str, str]:
    env = os.environ.copy()
    configured = env.get("JAVA_HOME", "")
    if configured and (Path(configured) / "bin" / "java").is_file():
        return env
    candidates = [
        Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
    ]
    for candidate in candidates:
        if (candidate / "bin" / "java").is_file():
            env["JAVA_HOME"] = str(candidate)
            env["PATH"] = f"{candidate / 'bin'}{os.pathsep}{env.get('PATH', '')}"
            return env
    return env


def parse_adb_devices(output: str) -> tuple[list[MobileDevice], list[str]]:
    devices: list[MobileDevice] = []
    unavailable: list[str] = []
    for raw in output.splitlines()[1:]:
        line = raw.strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        serial, state = fields[0], fields[1]
        attributes = {
            key: value
            for item in fields[2:]
            if ":" in item
            for key, value in [item.split(":", 1)]
        }
        if state != "device":
            unavailable.append(f"Android {serial}: {state}")
            continue
        name = attributes.get(
            "model", attributes.get("device", "Android device")
        ).replace("_", " ")
        devices.append(MobileDevice("android", serial, name))
    return devices, unavailable


def discover_android_devices() -> tuple[list[MobileDevice], list[str]]:
    adb = _find_adb()
    if not adb:
        return [], ["Android: adb not found"]
    result = _run([adb, "devices", "-l"], capture=True)
    if result.returncode != 0:
        detail = (
            (result.stderr or result.stdout or "adb failed").strip().splitlines()[-1]
        )
        return [], [f"Android: {detail}"]
    return parse_adb_devices(result.stdout or "")


def parse_devicectl_devices(payload: dict) -> list[MobileDevice]:
    devices: list[MobileDevice] = []
    for item in payload.get("result", {}).get("devices", []):
        hardware = item.get("hardwareProperties", {})
        properties = item.get("deviceProperties", {})
        connection = item.get("connectionProperties", {})
        if hardware.get("platform") != "iOS" or hardware.get("reality") != "physical":
            continue
        if properties.get("bootState") != "booted":
            continue
        if connection.get("pairingState") != "paired":
            continue
        identifier = hardware.get("udid") or item.get("identifier")
        if not identifier:
            continue
        devices.append(
            MobileDevice(
                "ios",
                str(identifier),
                str(
                    properties.get("name") or hardware.get("marketingName") or "iPhone"
                ),
            )
        )
    return devices


def discover_ios_devices() -> tuple[list[MobileDevice], list[str]]:
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        return [], ["iOS: Xcode command-line tools are unavailable"]
    env = os.environ.copy()
    full_xcode = Path("/Applications/Xcode.app/Contents/Developer")
    if full_xcode.is_dir():
        env["DEVELOPER_DIR"] = str(full_xcode)
    with tempfile.NamedTemporaryFile(suffix=".json") as handle:
        result = _run(
            ["xcrun", "devicectl", "list", "devices", "--json-output", handle.name],
            env=env,
            capture=True,
        )
        if result.returncode != 0:
            detail = (
                (result.stderr or result.stdout or "devicectl failed")
                .strip()
                .splitlines()[-1]
            )
            return [], [f"iOS: {detail}"]
        try:
            payload = json.loads(Path(handle.name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], [f"iOS: could not read devicectl output ({exc})"]
    return parse_devicectl_devices(payload), []


def discover_mobile_devices() -> tuple[list[MobileDevice], list[str]]:
    android, android_notes = discover_android_devices()
    ios, ios_notes = discover_ios_devices()
    return android + ios, android_notes + ios_notes


def print_mobile_devices(
    devices: Iterable[MobileDevice], notes: Iterable[str] = ()
) -> None:
    materialized = list(devices)
    if materialized:
        print("Attached mobile devices:")
        for device in materialized:
            print(f"  • {device.platform.upper():7} {device.label}")
    else:
        print("No eligible attached mobile devices found.")
    for note in notes:
        print(f"  ℹ {note}")


def _resolve_native_root(value: str | None, project_root: Path) -> Path:
    candidate = (
        Path(value).expanduser().resolve()
        if value
        else project_root / "apps" / "mobile"
    )
    if (candidate / "apps" / "mobile").is_dir():
        candidate = candidate / "apps" / "mobile"
    if not (candidate / "android").is_dir() and not (candidate / "ios").is_dir():
        raise MobileInstallError(
            "Native mobile sources were not found. Run this from a Fabric source checkout "
            "or pass --native-source /path/to/fabric/apps/mobile."
        )
    return candidate


def _choose_device(
    devices: list[MobileDevice],
    *,
    install_mode: str,
    android_serial: str,
    ios_device: str,
) -> MobileDevice | None:
    if android_serial and ios_device:
        raise MobileInstallError(
            "--android-serial and --ios-device are mutually exclusive."
        )
    if android_serial:
        if install_mode not in {"auto", "android"}:
            raise MobileInstallError(
                "--android-serial requires --install android (or auto)."
            )
        install_mode = "android"
    elif ios_device:
        if install_mode not in {"auto", "ios"}:
            raise MobileInstallError("--ios-device requires --install ios (or auto).")
        install_mode = "ios"
    if install_mode == "none":
        return None
    candidates = devices
    if install_mode in {"android", "ios"}:
        candidates = [
            device for device in candidates if device.platform == install_mode
        ]
    if android_serial:
        candidates = [
            device
            for device in candidates
            if device.platform == "android" and device.identifier == android_serial
        ]
    if ios_device:
        candidates = [
            device
            for device in candidates
            if device.platform == "ios" and device.identifier == ios_device
        ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        if install_mode == "auto":
            return None
        raise MobileInstallError(f"No eligible {install_mode} device is attached.")
    choices = ", ".join(device.label for device in candidates)
    raise MobileInstallError(
        "Multiple eligible devices are attached; select one with --android-serial "
        f"or --ios-device. Found: {choices}"
    )


def _install_android(device: MobileDevice, native_root: Path, *, launch: bool) -> None:
    adb = _find_adb()
    if not adb:
        raise MobileInstallError(
            "adb was not found. Install Android platform-tools first."
        )
    android_root = native_root / "android"
    windows = _is_windows()
    gradlew = android_root / ("gradlew.bat" if windows else "gradlew")
    if not gradlew.is_file():
        raise MobileInstallError(f"Gradle wrapper is missing: {gradlew}")
    gradle_command = (
        [os.environ.get("COMSPEC", "cmd.exe"), "/c", str(gradlew)]
        if windows
        else [str(gradlew)]
    )
    print(f"→ Building Fabric for {device.label}...")
    result = _run(
        [*gradle_command, "--no-daemon", ":app:assembleDebug"],
        cwd=android_root,
        env=_java_environment(),
    )
    if result.returncode != 0:
        raise MobileInstallError("Android debug build failed; see Gradle output above.")
    apk = android_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise MobileInstallError(
            f"Android build completed but the APK is missing: {apk}"
        )
    result = _run([adb, "-s", device.identifier, "install", "-r", "-t", str(apk)])
    if result.returncode != 0:
        raise MobileInstallError(
            "adb install failed; unlock and authorize the device, then retry."
        )
    if launch:
        result = _run([
            adb,
            "-s",
            device.identifier,
            "shell",
            "am",
            "start",
            "-n",
            f"{ANDROID_BUNDLE_ID}/.MainActivity",
        ])
        if result.returncode != 0:
            raise MobileInstallError(
                "Fabric installed, but Android could not launch it."
            )
    print(f"  ✓ Installed Fabric on {device.name}")


def _available_ios_teams() -> list[str]:
    result = _run(
        ["security", "find-identity", "-v", "-p", "codesigning"], capture=True
    )
    if result.returncode != 0:
        return []
    teams: list[str] = []
    for line in (result.stdout or "").splitlines():
        match = re.search(r'"Apple Development: .+ \(([A-Z0-9]{10})\)"', line)
        if match and match.group(1) not in teams:
            teams.append(match.group(1))
    return teams


def _install_ios(
    device: MobileDevice,
    native_root: Path,
    *,
    launch: bool,
    team: str,
) -> None:
    if sys.platform != "darwin":
        raise MobileInstallError("Physical iOS installation requires macOS and Xcode.")
    ios_root = native_root / "ios"
    project = ios_root / "FabricMobile.xcodeproj"
    if not shutil.which("xcodegen"):
        raise MobileInstallError(
            "xcodegen was not found. Install it with: brew install xcodegen"
        )
    teams = _available_ios_teams()
    if team:
        if teams and team not in teams:
            raise MobileInstallError(
                f"No valid Apple Development identity found for team {team}."
            )
    elif len(teams) == 1:
        team = teams[0]
    elif len(teams) > 1:
        raise MobileInstallError(
            "Multiple Apple Development teams are available; choose one with --ios-team TEAM_ID."
        )
    else:
        raise MobileInstallError(
            "No Apple Development signing identity is available. Sign into Xcode and create one first."
        )

    generated = _run(["xcodegen", "generate"], cwd=ios_root)
    if generated.returncode != 0 or not project.is_dir():
        raise MobileInstallError("xcodegen failed to generate the iOS project.")

    env = os.environ.copy()
    xcode = Path("/Applications/Xcode.app/Contents/Developer")
    if xcode.is_dir():
        env["DEVELOPER_DIR"] = str(xcode)
    with tempfile.TemporaryDirectory(prefix="fabric-ios-device-") as derived:
        print(f"→ Building and signing Fabric for {device.label}...")
        result = _run(
            [
                "xcodebuild",
                "-project",
                str(project),
                "-scheme",
                "Fabric",
                "-configuration",
                "Debug",
                "-destination",
                f"id={device.identifier}",
                "-derivedDataPath",
                derived,
                "-allowProvisioningUpdates",
                f"DEVELOPMENT_TEAM={team}",
                "CODE_SIGN_STYLE=Automatic",
                "build",
            ],
            cwd=ios_root,
            env=env,
            capture=True,
        )
        if result.returncode != 0:
            output = f"{result.stdout or ''}\n{result.stderr or ''}"
            if output.strip():
                print(output.strip(), file=sys.stderr)
            if "No Account for Team" in output:
                raise MobileInstallError(
                    f"Xcode has no signed-in account for Apple team {team}. "
                    "Open Xcode → Settings → Accounts, sign in to that team, "
                    "then retry the command."
                )
            if "No profiles for" in output:
                raise MobileInstallError(
                    "Xcode could not create or find a development provisioning "
                    "profile for Fabric. Open the generated project in Xcode, "
                    "select the Fabric target's Signing & Capabilities tab, "
                    "choose the team, then retry the command."
                )
            raise MobileInstallError(
                "iOS build/signing failed. Open the generated project in Xcode "
                "to resolve team, trust, or provisioning errors, then retry."
            )
        app = Path(derived) / "Build" / "Products" / "Debug-iphoneos" / "Fabric.app"
        if not app.is_dir():
            raise MobileInstallError(
                f"iOS build completed but the app bundle is missing: {app}"
            )
        result = _run(
            [
                "xcrun",
                "devicectl",
                "device",
                "install",
                "app",
                "--device",
                device.identifier,
                str(app),
            ],
            env=env,
        )
        if result.returncode != 0:
            raise MobileInstallError(
                "devicectl could not install Fabric; unlock and trust the iPhone, then retry."
            )
    if launch:
        result = _run(
            [
                "xcrun",
                "devicectl",
                "device",
                "process",
                "launch",
                "--device",
                device.identifier,
                IOS_BUNDLE_ID,
            ],
            env=env,
        )
        if result.returncode != 0:
            raise MobileInstallError(
                "Fabric installed, but devicectl could not launch it."
            )
    print(f"  ✓ Installed Fabric on {device.name}")


def install_native_mobile(
    *,
    project_root: Path,
    install_mode: str,
    native_source: str | None = None,
    android_serial: str = "",
    ios_device: str = "",
    ios_team: str = "",
    launch: bool = True,
) -> MobileDevice | None:
    """Install on one unambiguous attached device and return that device."""
    if install_mode == "none":
        return None
    devices, notes = discover_mobile_devices()
    try:
        device = _choose_device(
            devices,
            install_mode=install_mode,
            android_serial=android_serial,
            ios_device=ios_device,
        )
    except MobileInstallError as exc:
        selected_platform = (
            "android"
            if android_serial or install_mode == "android"
            else "ios"
            if ios_device or install_mode == "ios"
            else ""
        )
        relevant_notes = [
            note
            for note in notes
            if not selected_platform or note.lower().startswith(selected_platform)
        ]
        detail = f" Discovery: {'; '.join(relevant_notes)}" if relevant_notes else ""
        raise MobileInstallError(f"{exc}{detail}") from exc
    if device is None:
        print_mobile_devices(devices, notes)
        return None
    native_root = _resolve_native_root(native_source, project_root)
    if device.platform == "android":
        _install_android(device, native_root, launch=launch)
    else:
        _install_ios(device, native_root, launch=launch, team=ios_team)
    return device
