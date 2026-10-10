"""System log and crash logs, for bug reports.

logs/system.log - the latest state of the app, rewritten on app start,
translation/patch start and finish, and app close. Only what a developer needs
to reproduce a report: app version, OS, settings (API keys redacted), the
local LLM server's own report and the last run's numbers. Python/Qt versions
are not included - they are fixed per release, so the app version implies them.
Previous reports are kept as system.1.log ... system.4.log (5 files at most).

logs/crash_YYYYMMDD-HHMMSS.log - written when the app crashes:
- an unhandled Python exception (main thread or a worker thread), and
- a hard crash in native code (Qt), via faulthandler. A native crash cannot run
  Python code, so faulthandler writes the stack into logs/.fault.tmp; the next
  start turns a non-empty .fault.tmp into a dated crash log.
Each crash log ends with the system report as it was at the time. The newest
MAX_CRASH_LOGS are kept.

Nothing here may break the app: every failure is swallowed.
"""
from __future__ import annotations

import faulthandler
import json
import logging
import os
import platform
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("Diagnostics")

BACKUPS = 4               # system.log + 4 backups = 5 files at most
MAX_CRASH_LOGS = 10
REPORT_NAME = "system"
FAULT_FILE = ".fault.tmp"

_lock = threading.Lock()
_last_run: Dict[str, Any] = {}
_server_info: Dict[str, Any] = {}
_last_settings: Dict[str, Any] = {}
_fault_fh = None

#: Settings whose values must never be written to a file someone may share.
SECRET_SUFFIXES = ("_api_key", "_password", "_secret")


def _logs_dir(folder: Optional[Path]) -> Path:
    if folder is not None:
        return folder
    from src.utils.app_paths import get_logs_dir
    return get_logs_dir()


def redact_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (settings or {}).items():
        if key.endswith(SECRET_SUFFIXES) or key == "api_key":
            out[key] = "<set>" if value else ""
        else:
            out[key] = value
    return out


def _app_version() -> str:
    try:
        from version import VERSION
        return str(VERSION)
    except Exception:
        return "unknown"


def _get_json(url: str, timeout: float = 3.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - local server
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def probe_local_server(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the local LLM server what it is running (llama.cpp: /props)."""
    base = str(settings.get("local_llm_url") or "http://localhost:8080/v1").rstrip("/")
    root = base[:-3] if base.endswith("/v1") else base
    info: Dict[str, Any] = {"url": base}
    models = _get_json(base + "/models")
    if isinstance(models, dict) and "data" in models:
        info["models"] = [m.get("id") for m in models.get("data", []) if isinstance(m, dict)]
    else:
        info["models"] = models
    props = _get_json(root + "/props")
    if isinstance(props, dict) and "error" not in props:
        dgs = props.get("default_generation_settings") or {}
        info["model_path"] = props.get("model_path")
        info["server_build"] = props.get("build_info")
        info["slots"] = props.get("total_slots")
        info["context_per_slot"] = dgs.get("n_ctx") or props.get("n_ctx")
    elif isinstance(props, dict):
        info["props"] = props.get("error")
    return info


def record_run(stats: Dict[str, Any]) -> None:
    """Remember the latest translation run's numbers for the next report."""
    _last_run.clear()
    _last_run.update(stats)


def _section(title: str) -> str:
    return f"\n[{title}]\n"


def _kv(data: Dict[str, Any]) -> str:
    lines = []
    for key in sorted(data):
        value = data[key]
        if isinstance(value, str) and "\n" in value:
            # Multi-line values (custom prompt): indent so the file stays readable.
            body = "\n".join("    " + line for line in value.splitlines())
            lines.append(f"{key}:\n{body}")
        else:
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value}")
    return "\n".join(lines) + "\n"


def render_report(event: str, settings: Dict[str, Any]) -> str:
    text = (
        "RPGM Localizer system log\n"
        f"event   = {event}\n"
        f"time    = {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"version = {_app_version()}\n"
        f"os      = {platform.platform()}\n"
    )
    text += _section("settings") + _kv(redact_settings(settings))
    if _server_info:
        text += _section("local llm server") + _kv(_server_info)
    if _last_run:
        text += _section("last translation run") + _kv(_last_run)
    return text


def _rotate(folder: Path) -> Path:
    current = folder / f"{REPORT_NAME}.log"
    if current.exists():
        (folder / f"{REPORT_NAME}.{BACKUPS}.log").unlink(missing_ok=True)
        for n in range(BACKUPS - 1, 0, -1):
            src = folder / f"{REPORT_NAME}.{n}.log"
            if src.exists():
                src.replace(folder / f"{REPORT_NAME}.{n + 1}.log")
        current.replace(folder / f"{REPORT_NAME}.1.log")
    return current


def write_report(event: str, settings: Optional[Dict[str, Any]] = None,
                 probe_server: bool = False, folder: Optional[Path] = None) -> Optional[Path]:
    """Write logs/system.log for `event`. Returns the path, or None on failure."""
    if folder is None and os.environ.get("RPGM_NO_DIAGNOSTICS"):
        return None          # test runs must not overwrite the user's report
    try:
        settings = dict(settings or {})
        _last_settings.clear()
        _last_settings.update(settings)
        if probe_server and settings.get("engine") in ("local_llm", "hy_mt2"):
            _server_info.clear()
            _server_info.update(probe_local_server(settings))
        text = render_report(event, settings)
        out = _logs_dir(folder)
        with _lock:
            out.mkdir(parents=True, exist_ok=True)
            path = _rotate(out)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        return path
    except Exception as exc:
        logger.debug("System log failed (%s): %s", type(exc).__name__, exc)
        return None


# --------------------------------------------------------------------------
# Crash logs
# --------------------------------------------------------------------------

def _prune_crash_logs(folder: Path) -> None:
    crashes = sorted(folder.glob("crash_*.log"))
    for old in crashes[:-MAX_CRASH_LOGS]:
        old.unlink(missing_ok=True)


def write_crash_log(details: str, folder: Optional[Path] = None,
                    when: Optional[float] = None) -> Optional[Path]:
    try:
        out = _logs_dir(folder)
        out.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(when or time.time()))
        path = out / f"crash_{stamp}.log"
        n = 1
        while path.exists():
            n += 1
            path = out / f"crash_{stamp}_{n}.log"
        text = (
            "RPGM Localizer crash log\n"
            f"time    = {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(when or time.time()))}\n"
            f"version = {_app_version()}\n"
            f"os      = {platform.platform()}\n"
            + _section("crash") + details.rstrip() + "\n"
            + _section("state at the time") + render_report("crash", dict(_last_settings)).split("\n", 1)[1]
        )
        path.write_text(text, encoding="utf-8")
        _prune_crash_logs(out)
        return path
    except Exception as exc:
        logger.debug("Crash log failed (%s): %s", type(exc).__name__, exc)
        return None


def collect_native_crash(folder: Optional[Path] = None) -> Optional[Path]:
    """Turn a stack left by faulthandler in the last session into a crash log."""
    try:
        fault = _logs_dir(folder) / FAULT_FILE
        if fault.exists() and fault.stat().st_size > 0:
            details = "Native crash (the app closed without a Python error):\n" + \
                fault.read_text(encoding="utf-8", errors="replace")
            path = write_crash_log(details, folder, when=fault.stat().st_mtime)
            fault.write_text("", encoding="utf-8")
            return path
    except Exception as exc:
        logger.debug("Collecting native crash failed: %s", exc)
    return None


def install_crash_handlers(folder: Optional[Path] = None) -> None:
    """Call once at start-up, before the Qt event loop."""
    global _fault_fh
    if os.environ.get("RPGM_NO_DIAGNOSTICS") and folder is None:
        return
    collect_native_crash(folder)
    try:
        out = _logs_dir(folder)
        out.mkdir(parents=True, exist_ok=True)
        _fault_fh = open(out / FAULT_FILE, "w", encoding="utf-8")
        faulthandler.enable(file=_fault_fh, all_threads=True)
    except Exception as exc:
        logger.debug("faulthandler unavailable: %s", exc)

    previous_hook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        if not issubclass(exc_type, KeyboardInterrupt):
            write_crash_log("Unhandled exception:\n" + "".join(
                traceback.format_exception(exc_type, exc, tb)), folder)
        previous_hook(exc_type, exc, tb)

    def _thread_hook(args):
        if args.exc_type is not SystemExit:
            write_crash_log(f"Unhandled exception in thread {args.thread.name if args.thread else '?'}:\n"
                            + "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                                 args.exc_traceback)), folder)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook


def close_crash_handlers() -> None:
    """Normal exit: stop faulthandler and leave an empty .fault.tmp behind."""
    global _fault_fh
    try:
        faulthandler.disable()
        if _fault_fh is not None:
            _fault_fh.close()
            Path(_fault_fh.name).write_text("", encoding="utf-8")
            _fault_fh = None
    except Exception:
        pass
