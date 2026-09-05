"""Repository checks that need no Codex-internal scripts or online services."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/sketchforge"
sys.path.insert(0, str(SKILL / "scripts"))
from css_art import __version__


def main():
    manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == ROOT.name == "sketchforge"
    assert manifest["version"] == __version__
    assert manifest["license"] == "MIT"
    assert (ROOT / manifest["skills"]).resolve() == SKILL.parent.resolve()
    assert "Copyright (c) 2026 qiguai2233" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: sketchforge\n")
    assert len(text.splitlines()) < 100
    for link in ("references/tuning.md", "scripts/image_to_css.py", "requirements.txt"):
        assert (SKILL / link).is_file(), link
    subprocess.run([sys.executable, "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=ROOT, check=True)
    print("Plugin metadata, skill resources and regression tests passed.")


if __name__ == "__main__":
    main()
