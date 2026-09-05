import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package", ROOT / "scripts/package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def test_clean_deterministic_self_contained_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            first = package.package(folder)
            second = package.package(folder)
            self.assertEqual(first, second)
            for path in folder.glob("*.zip"):
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    self.assertTrue(all(".venv" not in name and ".work" not in name and "__pycache__" not in name for name in names))
                    self.assertIn("sketchforge/LICENSE", names)
                    if "-skill" in path.name:
                        archive.extractall(folder / "skill")
                    else:
                        self.assertIn("sketchforge/.codex-plugin/plugin.json", names)
            cli = folder / "skill/sketchforge/scripts/image_to_css.py"
            # -S disables all third-party site packages: audit/help remains portable.
            result = subprocess.run([sys.executable, "-S", str(cli), "--version"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "0.2.0")
