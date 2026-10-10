"""Size-capped, rotating log of LLM request/response payloads.

Payload dumping used to write one file per request and per response, forever:
a long run left thousands of files behind. Now each kind goes into a rolling
set of JSON Lines files:

    request_1.jsonl ... request_5.jsonl
    response_1.jsonl ... response_5.jsonl

_1 is the oldest, the highest number is the one being written. When the
current file passes MAX_FILE_BYTES a new one is started; when that would be
the (MAX_FILES + 1)th, _1 is deleted and the rest shift down (_2 -> _1, ...).
So the folder never holds more than 2 x MAX_FILES x MAX_FILE_BYTES (500 MB).

JSON Lines (one JSON object per line) rather than one big .json array, so a
record can be appended without rewriting the file and a crash mid-write loses
at most the last line. Every record carries an exchange id so a request and its
response can be matched across the two files.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILES = 5
KINDS = ("request", "response")

_lock = threading.Lock()
_LEGACY_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]+-(request|response)\.json$")


def _numbered(folder: Path, kind: str) -> list[tuple[int, Path]]:
    found = []
    for p in folder.glob(f"{kind}_*.jsonl"):
        m = re.fullmatch(rf"{kind}_(\d+)\.jsonl", p.name)
        if m:
            found.append((int(m.group(1)), p))
    return sorted(found)


def _rotate(folder: Path, kind: str) -> Path:
    """Return the file to append to, rotating if the current one is full."""
    files = _numbered(folder, kind)
    if files:
        n, current = files[-1]
        if current.stat().st_size < MAX_FILE_BYTES:
            return current
        n += 1
    else:
        n = 1
    if n > MAX_FILES:
        # Drop the oldest, shift the rest down, write to the last slot.
        files[0][1].unlink(missing_ok=True)
        for idx, (_, path) in enumerate(files[1:], start=1):
            path.replace(folder / f"{kind}_{idx}.jsonl")
        n = MAX_FILES
    return folder / f"{kind}_{n}.jsonl"


def _append(folder: Path, kind: str, record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False) + "\n"
    path = _rotate(folder, kind)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)


def fold_legacy_files(folder: Path) -> int:
    """Move old one-file-per-exchange dumps into the rotating logs, then delete them."""
    legacy = sorted(p for p in folder.glob("*.json") if _LEGACY_RE.match(p.name))
    moved = 0
    for p in legacy:
        kind = _LEGACY_RE.match(p.name).group(1)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {"unreadable": p.name}
        stamp = p.name[:15]
        _append(folder, kind, {"time": stamp, "id": p.name.split("-")[2], "legacy": True, "data": data})
        p.unlink(missing_ok=True)
        moved += 1
    return moved


def write(folder: Path, kind: str, data: Any, exchange_id: Optional[str] = None) -> None:
    if kind not in KINDS:
        kind = "response"
    with _lock:
        folder.mkdir(parents=True, exist_ok=True)
        if not getattr(write, "_folded", False):
            fold_legacy_files(folder)
            write._folded = True  # type: ignore[attr-defined]
        record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "id": exchange_id or "",
            "data": {"raw": data} if isinstance(data, str) else data,
        }
        _append(folder, kind, record)


def total_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.glob("*.jsonl")) if folder.exists() else 0
