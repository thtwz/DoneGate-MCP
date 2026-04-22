from __future__ import annotations

import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from donegate_mcp.config import DEFAULT_ENCODING
from donegate_mcp.errors import StorageError


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    try:
        with NamedTemporaryFile("w", encoding=DEFAULT_ENCODING, dir=path.parent, delete=False) as tmp:
            json.dump(data, tmp, indent=2, sort_keys=True)
            tmp.write("\n")
            tmp.flush()
            Path(tmp.name).replace(path)
    except OSError as exc:
        raise StorageError(f"failed to write json {path}: {exc}") from exc


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding=DEFAULT_ENCODING) as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise StorageError(f"missing file: {path}") from exc
    except OSError as exc:
        raise StorageError(f"failed to read json {path}: {exc}") from exc


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    try:
        with path.open("a", encoding=DEFAULT_ENCODING) as handle:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")
    except OSError as exc:
        raise StorageError(f"failed to append jsonl {path}: {exc}") from exc


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    try:
        path.write_text(content, encoding=DEFAULT_ENCODING)
    except OSError as exc:
        raise StorageError(f"failed to write text {path}: {exc}") from exc


def make_executable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | 0o111)
    except OSError as exc:
        raise StorageError(f"failed to chmod executable {path}: {exc}") from exc
