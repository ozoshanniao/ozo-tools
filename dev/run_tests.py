"""Run each synthetic regression in an isolated Blender process."""
from pathlib import Path
import argparse
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--blender", default="blender")
args = parser.parse_args()
(root / "outputs").mkdir(exist_ok=True)
subprocess.run([sys.executable, str(root / "dev" / "zip_build.py")], check=True)
failures = []
for test in sorted((root / "tests").glob("test_*.py")):
    log = root / "outputs" / (test.stem + ".log")
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run([args.blender, "--background", "--factory-startup",
            "--python-exit-code", "1", "--python", str(test)], cwd=root,
            stdout=output, stderr=subprocess.STDOUT)
    print(("PASS" if result.returncode == 0 else "FAIL") + " " + test.name, flush=True)
    if result.returncode:
        failures.append(test.name)
print(f"{len(list((root / 'tests').glob('test_*.py'))) - len(failures)} passed; {len(failures)} failed")
sys.exit(bool(failures))
