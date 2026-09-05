"""Build deterministic plugin/skill source archives from an explicit allowlist."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/sketchforge"


def source_files(root):
    allowed_suffixes = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".png", ".html"}
    return sorted(path for path in root.rglob("*") if path.is_file()
                  and "__pycache__" not in path.parts and path.suffix in allowed_suffixes)


def write_archive(destination, entries):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            data = path.read_bytes()
            if path.suffix != ".png":
                data = data.replace(b"\r\n", b"\n")
            archive.writestr(info, data)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def package(output):
    version = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    plugin_entries = [(f"sketchforge/{path.relative_to(ROOT).as_posix()}", path)
                      for folder in ("skills", ".codex-plugin", "scripts", "tests", "docs", ".github") for path in source_files(ROOT / folder)]
    plugin_entries += [(f"sketchforge/{name}", ROOT / name) for name in ("LICENSE", "README.md", ".gitignore", ".gitattributes")]
    skill_entries = [(f"sketchforge/{path.relative_to(SKILL).as_posix()}", path) for path in source_files(SKILL)]
    skill_entries.append(("sketchforge/LICENSE", ROOT / "LICENSE"))
    results = []
    for kind, entries in (("plugin", plugin_entries), ("skill", skill_entries)):
        path = output / f"sketchforge-{version}-{kind}.zip"
        results.append(f"{write_archive(path, entries)}  {path.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(results) + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    print("\n".join(package(parser.parse_args().output)))
