"""Launch/build-script contracts, using a fake runtime and no game data.

Run with: python3 -m unittest discover -s tests/linux -v
These tests do not compile or validate the recompiled game.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AppRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rrxx-linux-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.appdir = self.base / "App Dir"
        (self.appdir / "usr/bin").mkdir(parents=True)
        (self.appdir / "usr/lib").mkdir()
        self.apprun = self.appdir / "AppRun"
        shutil.copyfile(ROOT / "packaging/linux/AppRun", self.apprun)
        runtime = self.appdir / "usr/bin/rumble_roses_xx"
        runtime.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd(), "
            "'env': {key: os.environ.get(key) for key in "
            "['RRXX_GAME_DIR', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', "
            "'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'LD_LIBRARY_PATH']}}))\n"
        )
        runtime.chmod(0o755)
        # Avoid displaying a GUI error dialog on hosts that have zenity.
        self.bin = self.base / "bin"
        self.bin.mkdir()
        zenity = self.bin / "zenity"
        zenity.write_text("#!/bin/sh\nexit 0\n")
        zenity.chmod(0o755)
        self.env = os.environ.copy()
        for key in list(self.env):
            if key.startswith(("RRXX_", "XDG_")) or key in ("APPIMAGE", "LD_LIBRARY_PATH"):
                self.env.pop(key)
        self.env.update(HOME=str(self.base / "home"), PATH=f"{self.bin}:/usr/bin:/bin")

    def run_app(self, *args, **env):
        return subprocess.run(
            ["/bin/sh", str(self.apprun), *args],
            cwd=self.base,
            env={**self.env, **env},
            text=True,
            capture_output=True,
            timeout=10,
        )

    def game_dir(self):
        game = self.base / "Game Dump"
        game.mkdir()
        (game / "default.xex").touch()  # Only tests directory selection.
        return game

    def payload(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_help_needs_neither_game_data_nor_portable_storage(self):
        image = self.base / "Game.AppImage"
        result = self.run_app("--portable", "--help", APPIMAGE=str(image))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--game-dir", result.stdout)
        self.assertFalse(Path(str(image) + ".portable").exists())

    def test_explicit_game_selection_is_absolute_and_passed_as_native_override(self):
        game = self.game_dir()
        payload = self.payload(self.run_app("--game-dir", game.name, "--", "--gpu_backend=vulkan"))
        self.assertEqual(payload["env"]["RRXX_GAME_DIR"], str(game))
        self.assertEqual(payload["args"], [f"--game_data_root={game}", "--gpu_backend=vulkan"])
        self.assertEqual(payload["cwd"], str(self.base))

    def test_explicit_game_selection_rejects_missing_xex(self):
        directory = self.base / "empty"
        directory.mkdir()
        result = self.run_app("--game-dir", str(directory))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("default.xex", result.stderr)

    def test_game_option_requires_a_value(self):
        result = self.run_app("--game-dir")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a directory", result.stderr)

    def test_portable_mode_overrides_host_xdg_locations_outside_appdir(self):
        image = self.base / "Portable Game.AppImage"
        payload = self.payload(self.run_app(
            "--portable", "--game-dir", str(self.game_dir()),
            APPIMAGE=str(image), XDG_DATA_HOME="/host/data", XDG_CONFIG_HOME="/host/config",
        ))
        sidecar = Path(str(image) + ".portable")
        for variable, suffix in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                                 ("XDG_CACHE_HOME", "cache"), ("XDG_STATE_HOME", "state")):
            self.assertEqual(payload["env"][variable], str(sidecar / suffix))
        self.assertTrue(sidecar.is_dir())
        self.assertNotIn(str(self.appdir), str(sidecar))

    def test_portable_environment_supports_extracted_appdir_and_custom_directory(self):
        destination = self.base / "Shared Portable Data"
        payload = self.payload(self.run_app(
            RRXX_PORTABLE="1", RRXX_PORTABLE_DIR=str(destination),
        ))
        self.assertEqual(payload["env"]["XDG_DATA_HOME"], str(destination / "data"))
        self.assertTrue(destination.is_dir())

    def test_existing_portable_sidecar_is_reused_without_flags(self):
        image = self.base / "Game.AppImage"
        sidecar = Path(str(image) + ".portable")
        sidecar.mkdir()
        payload = self.payload(self.run_app(APPIMAGE=str(image)))
        self.assertEqual(payload["env"]["XDG_DATA_HOME"], str(sidecar / "data"))

    def test_custom_portable_directory_automatically_enables_portable_mode(self):
        destination = self.base / "Portable Data"
        payload = self.payload(self.run_app(RRXX_PORTABLE_DIR=str(destination)))
        self.assertEqual(payload["env"]["XDG_CONFIG_HOME"], str(destination / "config"))
        self.assertTrue(destination.is_dir())

    def test_explicit_opt_out_preserves_host_xdg_despite_portable_sidecar(self):
        image = self.base / "Game.AppImage"
        Path(str(image) + ".portable").mkdir()
        data = self.base / "host data"
        payload = self.payload(self.run_app(APPIMAGE=str(image), RRXX_PORTABLE="0", XDG_DATA_HOME=str(data)))
        self.assertEqual(payload["env"]["XDG_DATA_HOME"], str(data))

    def test_normal_mode_defers_default_game_resolution_to_native_runtime(self):
        data = self.base / "custom data"
        payload = self.payload(self.run_app(XDG_DATA_HOME=str(data)))
        self.assertEqual(payload["env"]["XDG_DATA_HOME"], str(data))
        self.assertIsNone(payload["env"]["RRXX_GAME_DIR"])
        self.assertEqual(payload["args"], [])

    def test_arguments_with_spaces_and_native_options_are_preserved(self):
        payload = self.payload(self.run_app("--", "--log_file", "logs with spaces/game.log", "--help"))
        self.assertEqual(payload["args"], ["--log_file", "logs with spaces/game.log", "--help"])
        self.assertEqual(payload["env"]["LD_LIBRARY_PATH"], str(self.appdir / "usr/lib"))


@unittest.skipUnless(sys.platform == "linux" and os.uname().machine == "x86_64", "Linux x86_64 build script")
class BuildPreflightTests(unittest.TestCase):
    def run_build(self, *args):
        return subprocess.run(
            ["/bin/bash", str(ROOT / "scripts/linux/build.sh"), *args],
            text=True, capture_output=True, timeout=10,
        )

    def test_missing_game_files_fail_before_creating_build_directory(self):
        with tempfile.TemporaryDirectory(prefix="rrxx-build-preflight-") as directory:
            base = Path(directory)
            work = base / "build"
            result = self.run_build("--game-dir", str(base / "missing"), "--work-dir", str(work))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("default.xex", result.stderr)
            self.assertFalse(work.exists())

    def test_invalid_parallelism_fails_before_setup(self):
        result = self.run_build("--jobs", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive integer", result.stderr)

    def test_rejected_toolchain_fails_before_fetching_or_creating_workdir(self):
        with tempfile.TemporaryDirectory(prefix="rrxx-toolchain-preflight-") as directory:
            base = Path(directory)
            tools = base / "bin"
            tools.mkdir()
            fetched = base / "fetch-attempted"
            for name in ("git", "cmake", "ninja", "pkg-config"):
                tool = tools / name
                tool.write_text('#!/bin/sh\ntouch "$RRXX_TEST_FETCH_MARKER"\nexit 99\n')
                tool.chmod(0o755)
            compiler = tools / "unsupported-clang"
            compiler.write_text("#!/bin/sh\necho 'Unsupported C++23 toolchain' >&2\nexit 1\n")
            compiler.chmod(0o755)
            work = base / "build"
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "scripts/linux/build.sh"), "--sdk-only", "--work-dir", str(work)],
                env={**os.environ, "PATH": f"{tools}:/usr/bin:/bin", "CC": "/bin/true", "CXX": str(compiler),
                     "RRXX_TEST_FETCH_MARKER": str(fetched)},
                text=True, capture_output=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("C++23 toolchain check failed", result.stderr)
            self.assertFalse(work.exists())
            self.assertFalse(fetched.exists())

    def test_build_help_does_not_need_a_game_dump(self):
        result = self.run_build("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--sdk-only", result.stdout)


if __name__ == "__main__":
    unittest.main()
