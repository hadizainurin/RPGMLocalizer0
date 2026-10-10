"""Log of the messages the user was shown (toasts / notices).

logs/message_YYMMDD.log, one file per day, one line per message:

    14:05:12  [warning]  Translation Editor: 10 machine translations with damaged ...

So a user can look up what a popup said after it disappeared, and attach it to
a bug report. The newest MAX_DAYS files are kept.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

MAX_DAYS = 30
_lock = threading.Lock()


def _folder(folder: Optional[Path]) -> Path:
    if folder is not None:
        return folder
    from src.utils.app_paths import get_logs_dir
    return get_logs_dir()


def log_message(kind: str, title: str, message: str, folder: Optional[Path] = None,
                when: Optional[float] = None) -> Optional[Path]:
    if folder is None and os.environ.get("RPGM_NO_DIAGNOSTICS"):
        return None
    try:
        out = _folder(folder)
        stamp = time.localtime(when or time.time())
        path = out / f"message_{time.strftime('%y%m%d', stamp)}.log"
        # One line per message: newlines inside a message are flattened.
        text = " ".join(str(message or "").split())
        head = f"{title.strip()}: " if title and title.strip() else ""
        line = f"{time.strftime('%H:%M:%S', stamp)}  [{(kind or 'info').strip()}]  {head}{text}\n"
        with _lock:
            out.mkdir(parents=True, exist_ok=True)
            new_file = not path.exists()
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
            if new_file:
                for old in sorted(out.glob("message_*.log"))[:-MAX_DAYS]:
                    old.unlink(missing_ok=True)
        return path
    except Exception:
        return None
