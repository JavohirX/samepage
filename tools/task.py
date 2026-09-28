"""One runner. `python tools/task.py <verb>`."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _py(*args: str) -> int:
    return subprocess.call([sys.executable, *args], cwd=ROOT)


def verify() -> int:
    code = _py("-m", "pytest", "tests/domain", "tests/test_policy.py")
    if code != 0:
        return code
    print("pytest ok. With the stack up: python run.py .dogfood.toml")
    return 0


def inputs() -> int:
    lines = []
    for name in ("run.py", "fixtures.json"):
        digest = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        lines.append(f"{name} {digest}")
    path = ROOT / "receipts" / "inputs.txt"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(path.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str]) -> int:
    verb = argv[1] if len(argv) > 1 else "verify"
    if verb == "verify":
        return verify()
    if verb == "inputs":
        return inputs()
    if verb == "test":
        return _py("-m", "pytest")
    print("verbs: verify, test, inputs")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
