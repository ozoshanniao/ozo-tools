"""Build the extension ZIP from the same source used by the development session."""
from pathlib import Path
import sys
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "OZO_Tools"


def snapshot(source):
    files = {}
    for path in sorted(Path(source).rglob("*")):
        relative = path.relative_to(source)
        if path.is_file() and not any(
            part.startswith(".") or part == "__pycache__" for part in relative.parts
        ) and path.suffix not in {".pyc", ".pyo"}:
            files[relative.as_posix()] = path.read_bytes()
    if "__init__.py" not in files or "blender_manifest.toml" not in files:
        raise ValueError("Source must contain __init__.py and blender_manifest.toml")
    for name, content in files.items():
        if name.endswith(".py"):
            compile(content, str(Path(source) / name), "exec")
    tomllib.loads(files["blender_manifest.toml"].decode("utf-8"))
    return files


def build(source, destination):
    files = snapshot(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return files


if __name__ == "__main__":
    manifest = tomllib.loads((SOURCE / "blender_manifest.toml").read_text("utf-8"))
    output = ROOT / "dist" / f"OZO_Tools-{manifest['version']}.zip"
    build(SOURCE, output)
    print(f"ZIP ready: {output}")
