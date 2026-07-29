#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {
    ".env",
    "cookies.json",
    "auth",
    ".originals",
    "chrome-profile",
}
FORBIDDEN_PREFIXES = ("outputs/",)
SECRET_PATTERNS = {
    "GitHub token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{20,}"),
    "OpenAI key": re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(rb"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
}


def tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        ROOT / item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def forbidden_path(path: Path) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    parts = set(path.relative_to(ROOT).parts)
    return relative.startswith(FORBIDDEN_PREFIXES) or bool(parts & FORBIDDEN_PARTS)


def main() -> int:
    errors: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        if forbidden_path(path):
            errors.append(f"forbidden tracked path: {relative}")
            continue
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            continue
        data = path.read_bytes()
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(data):
                errors.append(f"{label} pattern found: {relative}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Secret and authorization-file check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
