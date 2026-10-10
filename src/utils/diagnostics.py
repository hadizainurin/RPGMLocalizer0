"""System log, translation log and crash logs, for bug reports.

logs/system.log - the configuration a translation ran with, written once when
the user starts a translation: app version, OS, engine, the model the server
has loaded (asked once per run), settings (API keys redacted) and what the
local LLM server reports about itself. Python/Qt versions are not included -
they are fixed per release, so the app version implies them.
Previous ones are kept as system_1.log ... system_4.log (5 files at most).

logs/translation.log - how that run went: started/ended, status (finished,
cancelled, error, or interrupted if the app was closed or crashed mid-run),
lines done / total, lines left, elapsed, and lines/min (only for a finished
run). Updated as the run progresses, so an abrupt end leaves the last state.
Previous runs are kept as translation_1.log ... translation_4.log.

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
RUN_LOG_NAME = "translation"
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


def model_name(info: Dict[str, Any]) -> str:
    """The model the server has loaded, from its /models list or model path."""
    models = info.get("models")
    if isinstance(models, list) and models:
        name = str(models[0] or "")
        return name.replace("\\", "/").rsplit("/", 1)[-1]
    path = info.get("model_path")
    if path:
        return str(path).replace("\\", "/").rsplit("/", 1)[-1]
    return ""


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
    engine = str(settings.get("engine", "") or "")
    model = model_name(_server_info) if engine in ("local_llm", "hy_mt2") else ""
    text = (
        "RPGM Localizer system log\n"
        f"event   = {event}\n"
        f"time    = {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"version = {_app_version()}\n"
        f"os      = {platform.platform()}\n"
        f"engine  = {engine}\n"
        f"model   = {model}\n"
    )
    text += _section("settings") + _kv(redact_settings(settings))
    if _server_info:
        text += _section("local llm server") + _kv(_server_info)
    return text


def _rotate(folder: Path, name: str = REPORT_NAME) -> Path:
    """name.log -> name_1.log -> ... -> name_4.log (dropped after that)."""
    current = folder / f"{name}.log"
    if current.exists():
        (folder / f"{name}_{BACKUPS}.log").unlink(missing_ok=True)
        for n in range(BACKUPS - 1, 0, -1):
            src = folder / f"{name}_{n}.log"
            if src.exists():
                src.replace(folder / f"{name}_{n + 1}.log")
        current.replace(folder / f"{name}_1.log")
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
# Translation log (one per run, updated while it runs)
# --------------------------------------------------------------------------

def _fmt_seconds(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def render_run(state: Dict[str, Any]) -> str:
    done, total = state.get("lines_done"), state.get("lines_total")
    finished = state.get("status") == "finished"
    rate = state.get("lines_per_min")
    lines = [
        "RPGM Localizer translation log",
        f"mode      = {state.get('mode', '')}",
        f"started   = {state.get('started', '')}",
        f"updated   = {state.get('updated', '')}",
        f"status    = {state.get('status', '')}",
        f"progress  = {'' if done is None else done} / {'' if total is None else total}",
        f"remaining = {'' if done is None or total is None else max(0, total - done)}",
        f"elapsed   = {_fmt_seconds(state.get('elapsed_seconds'))}",
        # Only meaningful for a run that got to the end.
        f"speed     = {f'{rate:.1f} lines/min' if finished and rate is not None else ''}",
    ]
    if state.get("message"):
        lines.append(f"result    = {state['message']}")
    return "\n".join(lines) + "\n"


def _read_status(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("status"):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def start_run_log(state: Dict[str, Any], folder: Optional[Path] = None) -> Optional[Path]:
    """Begin a translation log. A previous run still marked running was cut off."""
    if folder is None and os.environ.get("RPGM_NO_DIAGNOSTICS"):
        return None
    try:
        out = _logs_dir(folder)
        with _lock:
            out.mkdir(parents=True, exist_ok=True)
            current = out / f"{RUN_LOG_NAME}.log"
            if current.exists() and _read_status(current) == "running":
                text = current.read_text(encoding="utf-8").replace(
                    "status    = running", "status    = interrupted (app closed or crashed mid-run)")
                current.write_text(text, encoding="utf-8")
            path = _rotate(out, RUN_LOG_NAME)
            path.write_text(render_run(dict(state, status="running")), encoding="utf-8")
        return path
    except Exception as exc:
        logger.debug("Translation log failed: %s", exc)
        return None


def update_run_log(state: Dict[str, Any], folder: Optional[Path] = None) -> None:
    """Rewrite the current translation log in place (no rotation)."""
    if folder is None and os.environ.get("RPGM_NO_DIAGNOSTICS"):
        return
    try:
        out = _logs_dir(folder)
        path = out / f"{RUN_LOG_NAME}.log"
        tmp = path.with_suffix(".tmp")
        with _lock:
            tmp.write_text(render_run(state), encoding="utf-8")
            os.replace(tmp, path)
    except Exception as exc:
        logger.debug("Translation log update failed: %s", exc)


def mark_interrupted_runs(folder: Optional[Path] = None) -> None:
    """At start-up: a log still 'running' means the last run never ended."""
    if folder is None and os.environ.get("RPGM_NO_DIAGNOSTICS"):
        return
    try:
        current = _logs_dir(folder) / f"{RUN_LOG_NAME}.log"
        if current.exists() and _read_status(current) == "running":
            text = current.read_text(encoding="utf-8").replace(
                "status    = running", "status    = interrupted (app closed or crashed mid-run)")
            current.write_text(text, encoding="utf-8")
    except Exception:
        pass


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
    mark_interrupted_runs(folder)
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
    """Normal exit: stop faulthandler and remove its (empty) file.

    .fault.tmp only exists while the app runs: faulthandler needs a file that is
    already open when a native crash happens, because nothing can be created at
    that point. After a clean exit it is deleted; one left behind with content
    is a crash, and the next start turns it into crash_*.log.
    """
    global _fault_fh
    try:
        faulthandler.disable()
        if _fault_fh is not None:
            name = _fault_fh.name
            _fault_fh.close()
            _fault_fh = None
            path = Path(name)
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
    except Exception:
        pass
