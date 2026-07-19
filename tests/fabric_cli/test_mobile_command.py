from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

from fabric_cli.mobile_devices import (
    MobileDevice,
    MobileInstallError,
    _choose_device,
    _install_android,
    _install_ios,
    install_native_mobile,
    parse_adb_devices,
    parse_devicectl_devices,
)
from fabric_cli.subcommands.mobile import (
    build_mobile_parser,
    validate_mobile_install_selection,
)


def test_mobile_parser_defaults_to_secure_pairing_and_unambiguous_auto_install():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    handler = lambda _: None
    build_mobile_parser(subparsers, cmd_mobile=handler)

    args = parser.parse_args(["mobile"])

    assert args.func is handler
    assert args.host == "0.0.0.0"
    assert args.port == 9119
    assert args.install == "auto"
    assert args.no_qr is False
    assert args.skip_build is False


def test_mobile_parser_accepts_explicit_device_and_https_advertise_url():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    build_mobile_parser(subparsers, cmd_mobile=lambda _: None)

    args = parser.parse_args([
        "mobile",
        "--install",
        "ios",
        "--ios-device",
        "phone-1",
        "--ios-team",
        "TEAM123456",
        "--qr-url",
        "https://fabric.example.test",
    ])

    assert args.install == "ios"
    assert args.ios_device == "phone-1"
    assert args.ios_team == "TEAM123456"
    assert args.qr_url == "https://fabric.example.test"


def test_explicit_selector_sets_effective_platform_and_conflicts_fail():
    assert (
        validate_mobile_install_selection(
            argparse.Namespace(
                install="auto", android_serial="ANDROID-1", ios_device=""
            )
        )
        == "android"
    )
    assert (
        validate_mobile_install_selection(
            argparse.Namespace(install="auto", android_serial="", ios_device="IPHONE-1")
        )
        == "ios"
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        validate_mobile_install_selection(
            argparse.Namespace(
                install="auto", android_serial="ANDROID-1", ios_device="IPHONE-1"
            )
        )
    with pytest.raises(ValueError, match="requires --install android"):
        validate_mobile_install_selection(
            argparse.Namespace(install="ios", android_serial="ANDROID-1", ios_device="")
        )


def test_parse_adb_devices_separates_usable_and_unavailable_targets():
    devices, unavailable = parse_adb_devices(
        "List of devices attached\n"
        "emulator-5554 device product:sdk model:Pixel_9 device:emu transport_id:1\n"
        "R5 offline transport_id:2\n"
        "R6 unauthorized transport_id:3\n"
    )

    assert devices == [MobileDevice("android", "emulator-5554", "Pixel 9")]
    assert unavailable == ["Android R5: offline", "Android R6: unauthorized"]


def test_parse_devicectl_devices_requires_physical_paired_booted_ios():
    common = {
        "deviceProperties": {"bootState": "booted", "name": "My iPhone"},
        "connectionProperties": {"pairingState": "paired"},
        "hardwareProperties": {
            "platform": "iOS",
            "reality": "physical",
            "udid": "PHONE-1",
        },
    }
    simulator = {
        **common,
        "hardwareProperties": {**common["hardwareProperties"], "reality": "simulator"},
    }
    unpaired = {
        **common,
        "connectionProperties": {"pairingState": "unpaired"},
    }

    assert parse_devicectl_devices({
        "result": {"devices": [common, simulator, unpaired]}
    }) == [MobileDevice("ios", "PHONE-1", "My iPhone")]


def test_auto_install_only_selects_one_unambiguous_device():
    phone = MobileDevice("ios", "PHONE-1", "My iPhone")
    assert (
        _choose_device(
            [phone],
            install_mode="auto",
            android_serial="",
            ios_device="",
        )
        == phone
    )
    assert (
        _choose_device(
            [],
            install_mode="auto",
            android_serial="",
            ios_device="",
        )
        is None
    )

    with pytest.raises(MobileInstallError, match="Multiple eligible devices"):
        _choose_device(
            [phone, MobileDevice("android", "ANDROID-1", "Pixel")],
            install_mode="auto",
            android_serial="",
            ios_device="",
        )


def test_explicit_platform_does_not_silently_fall_back():
    with pytest.raises(MobileInstallError, match="No eligible android"):
        _choose_device(
            [MobileDevice("ios", "PHONE-1", "My iPhone")],
            install_mode="android",
            android_serial="",
            ios_device="",
        )


def test_install_none_does_not_probe_device_tooling(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "fabric_cli.mobile_devices.discover_mobile_devices",
        lambda: (_ for _ in ()).throw(
            AssertionError("device discovery should not run")
        ),
    )

    assert (
        install_native_mobile(
            project_root=tmp_path,
            install_mode="none",
        )
        is None
    )


def test_explicit_selector_surfaces_platform_discovery_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "fabric_cli.mobile_devices.discover_mobile_devices",
        lambda: (
            [],
            [
                "Android: adb not found",
                "iOS: Xcode command-line tools are unavailable",
            ],
        ),
    )

    with pytest.raises(MobileInstallError, match="adb not found"):
        install_native_mobile(
            project_root=tmp_path,
            install_mode="android",
            android_serial="ANDROID-1",
        )


def test_android_install_uses_windows_gradle_wrapper(monkeypatch, tmp_path):
    android_root = tmp_path / "android"
    gradlew = android_root / "gradlew.bat"
    apk = android_root / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    gradlew.parent.mkdir(parents=True)
    gradlew.write_text("@echo off\r\n")
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("fabric_cli.mobile_devices._is_windows", lambda: True)
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")
    monkeypatch.setattr("fabric_cli.mobile_devices._find_adb", lambda: "adb.exe")
    monkeypatch.setattr("fabric_cli.mobile_devices._run", fake_run)

    _install_android(
        MobileDevice("android", "ANDROID-1", "Pixel"),
        tmp_path,
        launch=False,
    )

    assert calls[0][0] == [
        "C:\\Windows\\System32\\cmd.exe",
        "/c",
        str(gradlew),
        "--no-daemon",
        ":app:assembleDebug",
    ]


def test_ios_signing_error_identifies_missing_xcode_account(monkeypatch, tmp_path):
    ios_root = tmp_path / "ios"
    (ios_root / "FabricMobile.xcodeproj").mkdir(parents=True)
    monkeypatch.setattr("fabric_cli.mobile_devices.sys.platform", "darwin")
    monkeypatch.setattr(
        "fabric_cli.mobile_devices.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        "fabric_cli.mobile_devices._available_ios_teams", lambda: ["TEAM123456"]
    )

    def fake_run(argv, **kwargs):
        if Path(argv[0]).name == "xcodebuild":
            assert kwargs["capture"] is True
            return subprocess.CompletedProcess(
                argv,
                65,
                stdout='error: No Account for Team "TEAM123456".',
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("fabric_cli.mobile_devices._run", fake_run)

    with pytest.raises(MobileInstallError, match="Xcode has no signed-in account"):
        _install_ios(
            MobileDevice("ios", "PHONE-1", "My iPhone"),
            tmp_path,
            launch=True,
            team="TEAM123456",
        )


def test_mobile_web_build_rebuilds_when_shared_source_is_newer(monkeypatch, tmp_path):
    from fabric_cli import main as cli_main

    web_dir = tmp_path / "apps" / "mobile-web"
    shared_source = tmp_path / "apps" / "shared" / "src" / "remote-session.ts"
    dist_index = tmp_path / "fabric_cli" / "mobile_web_dist" / "index.html"
    for path in (
        tmp_path / "package.json",
        tmp_path / "package-lock.json",
        web_dir / "package.json",
        web_dir / "index.html",
        web_dir / "vite.config.ts",
        web_dir / "tsconfig.json",
        tmp_path / "apps" / "shared" / "package.json",
        tmp_path / "apps" / "shared" / "tsconfig.json",
        shared_source,
        dist_index,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        os.utime(path, (100, 100))
    os.utime(shared_source, (200, 200))

    install = Mock(returncode=0)
    build = Mock(returncode=0, stdout="")
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("fabric_constants.find_node_executable", lambda _: "npm")
    monkeypatch.setattr(
        cli_main, "_run_npm_install_deterministic", lambda *args, **kwargs: install
    )
    monkeypatch.setattr(
        cli_main, "_run_with_idle_timeout", lambda *args, **kwargs: build
    )

    assert cli_main._build_mobile_web_ui(web_dir) is True


def test_mobile_auth_gate_fails_before_native_install(monkeypatch):
    from fabric_cli import main as cli_main

    install = Mock(side_effect=AssertionError("native install must not run"))
    monkeypatch.setattr(
        "fabric_cli.egress_startup.require_runtime_egress_available", lambda **_: None
    )
    monkeypatch.setattr(cli_main, "_sync_bundled_skills_quietly", lambda: None)
    monkeypatch.setattr(cli_main, "_build_mobile_web_ui", lambda _: True)
    monkeypatch.setattr(
        cli_main, "_maybe_setup_dashboard_auth_interactively", lambda _: None
    )
    monkeypatch.setattr("fabric_cli.plugins.discover_plugins", lambda: None)
    monkeypatch.setattr("fabric_cli.dashboard_auth.list_providers", lambda: [])
    monkeypatch.setattr("fabric_cli.web_server.should_require_auth", lambda _: True)
    monkeypatch.setattr("fabric_cli.mobile_devices.install_native_mobile", install)

    args = argparse.Namespace(
        devices=False,
        install="none",
        android_serial="",
        ios_device="",
        qr_url="",
        host="0.0.0.0",
        skip_build=False,
    )
    with pytest.raises(SystemExit, match="non-loopback binds require an auth provider"):
        cli_main.cmd_mobile(args)
    install.assert_not_called()
