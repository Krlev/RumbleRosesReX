"""Exercise packaging failure boundaries without invoking downloaded tools."""

import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/linux/package-appimage.sh"


@unittest.skipUnless(
    platform.system() == "Linux" and platform.machine() == "x86_64"
    and shutil.which("readelf"),
    "packaging requires Linux x86_64 and binutils",
)
class PackageGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rrxx-package-guards-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sdk = self.root / "sdk"
        (self.sdk / "lib").mkdir(parents=True)
        self.tool = self.root / "packaging-tool"
        self.marker = self.root / "tool-invoked"
        self.tool.write_text(
            '#!/bin/sh\nprintf invoked > "$RRXX_TEST_MARKER"\nexit 19\n'
        )
        self.tool.chmod(0o755)
        self.env = dict(os.environ, RRXX_TEST_MARKER=str(self.marker))
        self.output = self.root / "output.AppImage"
        self.binary = Path(shutil.which("true"))

    def run_package(self, *args):
        result = subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=self.env, text=True, capture_output=True,
        )
        self.assertFalse(self.marker.exists(), "guard failure must not invoke tools")
        return result

    def args(self, binary=None):
        return [
            "--binary", str(binary or self.binary), "--sdk", str(self.sdk),
            "--linuxdeploy", str(self.tool), "--appimagetool", str(self.tool),
            "--output", str(self.output),
        ]

    def assert_rejected(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        self.assertFalse(self.output.exists())

    def test_help_does_not_require_build_or_tools(self):
        result = self.run_package("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--runtime-file", result.stdout)

    def test_missing_required_binary(self):
        self.assert_rejected(self.run_package(), "Usage:")

    def test_missing_binary_is_rejected(self):
        self.assert_rejected(
            self.run_package(*self.args(self.root / "missing")), "not an executable"
        )

    def test_non_elf_binary_is_rejected(self):
        self.assert_rejected(
            self.run_package(*self.args(self.tool)), "not an ELF binary"
        )

    def test_missing_release_plugin_is_rejected(self):
        self.assert_rejected(
            self.run_package(*self.args()), "Release librexgpu-xenos.so not found"
        )

    def test_existing_output_is_preserved(self):
        original = b"existing user artifact"
        self.output.write_bytes(original)
        result = self.run_package(*self.args())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output already exists", result.stderr)
        self.assertEqual(self.output.read_bytes(), original)

    def test_missing_runtime_value(self):
        self.assert_rejected(
            self.run_package("--runtime-file"), "missing value for --runtime-file"
        )

    def test_missing_runtime_file_is_rejected(self):
        self.assert_rejected(
            self.run_package(*self.args(), "--runtime-file", str(self.root / "missing")),
            "runtime file is not readable",
        )

    def test_non_elf_runtime_is_rejected(self):
        runtime = self.root / "bad-runtime"
        runtime.write_bytes(b"not an ELF runtime")
        self.assert_rejected(
            self.run_package(*self.args(), "--runtime-file", str(runtime)),
            "not an ELF binary",
        )

    def test_wrong_architecture_runtime_is_rejected(self):
        # Preserve a valid ELF header but mark the machine as AArch64.
        image = bytearray(self.binary.read_bytes())
        image[18:20] = (183).to_bytes(2, "little")
        runtime = self.root / "aarch64-runtime"
        runtime.write_bytes(image)
        self.assert_rejected(
            self.run_package(*self.args(), "--runtime-file", str(runtime)),
            "not a Linux x86_64 binary",
        )


if __name__ == "__main__":
    unittest.main()
