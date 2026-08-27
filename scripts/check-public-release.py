#!/usr/bin/env python3
"""Fail when publication candidates contain common secrets or private endpoints."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
}
MAX_TEXT_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]


RULES = (
    Rule(
        "private IPv4 address",
        re.compile(
            r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])"
        ),
    ),
    Rule("Windows user profile path", re.compile(r"(?i)[a-z]:\\Users\\[^\\\s]+")),
    Rule("WSL user profile path", re.compile(r"/mnt/[a-z]/Users/[^/\s]+")),
    Rule(
        "private key material",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    Rule("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    Rule("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Rule("long sk-style token", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
)

ALLOWED_MATCHES = {
    "sk-replace-with-a-long-random-value",
}


def _git_tracked_files(root: Path) -> list[Path] | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root.as_posix()}",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    return [root / item.decode() for item in result.stdout.split(b"\0") if item]


def _workspace_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if not path.is_file():
            continue
        yield path


def publication_files(root: Path) -> list[Path]:
    tracked = _git_tracked_files(root)
    candidates = tracked if tracked is not None else list(_workspace_files(root))
    return sorted(
        path
        for path in candidates
        if path.is_file()
        and not any(
            part in IGNORED_DIRECTORIES for part in path.relative_to(root).parts
        )
    )


def scan_file(path: Path, root: Path) -> list[str]:
    if path.stat().st_size > MAX_TEXT_FILE_BYTES:
        return []
    raw = path.read_bytes()
    if b"\0" in raw:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[str] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            for match in rule.pattern.finditer(line):
                if match.group(0) in ALLOWED_MATCHES:
                    continue
                relative = path.relative_to(root).as_posix()
                findings.append(f"{relative}:{line_number}: {rule.name}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Optional files to scan instead of all publication candidates",
    )
    args = parser.parse_args()

    files = [path.resolve() for path in args.paths] or publication_files(ROOT)
    findings = [item for path in files for item in scan_file(path, ROOT)]
    if findings:
        print("Publication privacy scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print(f"Publication privacy scan passed ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
