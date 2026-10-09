"""
Editor Backend Module
=====================
PyQt6 bridge integrating EditorStore, QAbstractTableModel virtualization,
background project scanning, escape code safety, and surgical save operations.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    QThread,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)

from src.core.editor.editor_store import (
    ALL_FILES_ALIASES,
    ALL_FILES_LABEL,
    CATEGORY_LABELS,
    EditorStore,
)
from src.core.editor.syntax_checker import extract_escape_codes
from src.utils.backup import BackupManager
from src.utils.file_ops import safe_write
from src.utils.path_manager import get_cache_dir, get_project_id
from src.utils.paths import local_path_from_url


def _extract_entries_from_backup(
    file_path: str,
    backup_path: str,
    settings: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Extract text entries from a backup copy of *file_path*.

    Parsers key their extraction rules on the basename (e.g. ``Actors.json``), so the
    timestamped backup is first staged under its original name in a temp directory.
    Returns an empty list on any failure so scanning never aborts.
    """
    import shutil
    import tempfile
    from src.core.parser_factory import get_parser

    try:
        with tempfile.TemporaryDirectory(prefix="rpgm_editor_bak_") as tmp_dir:
            staged = os.path.join(tmp_dir, os.path.basename(file_path))
            shutil.copy2(backup_path, staged)

            # Stage companion .project schema for WOLF .dat databases so extraction succeeds
            if file_path.lower().endswith(".dat"):
                orig_project = os.path.splitext(file_path)[0] + ".project"
                bak_project = os.path.splitext(backup_path)[0] + ".project"
                staged_project = os.path.splitext(staged)[0] + ".project"
                if os.path.isfile(orig_project):
                    shutil.copy2(orig_project, staged_project)
                elif os.path.isfile(bak_project):
                    shutil.copy2(bak_project, staged_project)

            parser = get_parser(file_path, settings)
            if not parser:
                return []
            return list(parser.extract_text(staged))
    except Exception as exc:
        logging.getLogger("EditorBackend").debug(
            "Backup extraction failed for %s (%s): %s", file_path, backup_path, exc
        )
        return []


class EditorTableModel(QAbstractTableModel):
    """Virtualized table model providing O(1) data access to QML views."""

    IdRole = Qt.ItemDataRole.UserRole + 1
    FileNameRole = Qt.ItemDataRole.UserRole + 2
    JsonPathRole = Qt.ItemDataRole.UserRole + 3
    TagRole = Qt.ItemDataRole.UserRole + 4
    CategoryRole = Qt.ItemDataRole.UserRole + 5
    CategoryLabelRole = Qt.ItemDataRole.UserRole + 6
    OriginalTextRole = Qt.ItemDataRole.UserRole + 7
    TranslatedTextRole = Qt.ItemDataRole.UserRole + 8
    PrevContextRole = Qt.ItemDataRole.UserRole + 9
    NextContextRole = Qt.ItemDataRole.UserRole + 10
    IsModifiedRole = Qt.ItemDataRole.UserRole + 11
    LineCountRole = Qt.ItemDataRole.UserRole + 12
    HasWarningRole = Qt.ItemDataRole.UserRole + 13
    WarningMsgRole = Qt.ItemDataRole.UserRole + 14

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1  # List-style row representation with role properties

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]

        if role == self.IdRole:
            return row.get("id", 0)
        elif role == self.FileNameRole:
            return row.get("file_name", "")
        elif role == self.JsonPathRole:
            return row.get("json_path", "")
        elif role == self.TagRole:
            return row.get("tag", "")
        elif role == self.CategoryRole:
            return row.get("category", "")
        elif role == self.CategoryLabelRole:
            return CATEGORY_LABELS.get(row.get("category", "other"), "Other")
        elif role == self.OriginalTextRole:
            return row.get("original_text", "")
        elif role == self.TranslatedTextRole:
            return row.get("translated_text", "")
        elif role == self.PrevContextRole:
            return row.get("prev_context", "")
        elif role == self.NextContextRole:
            return row.get("next_context", "")
        elif role == self.IsModifiedRole:
            return bool(row.get("is_modified", 0))
        elif role == self.LineCountRole:
            return row.get("line_count", 1)
        elif role == self.HasWarningRole:
            return bool(row.get("has_warning", 0))
        elif role == self.WarningMsgRole:
            return row.get("warning_msg", "")
        elif role == Qt.ItemDataRole.DisplayRole:
            return row.get("original_text", "")

        return None

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.IdRole: QByteArray(b"entryId"),
            self.FileNameRole: QByteArray(b"fileName"),
            self.JsonPathRole: QByteArray(b"jsonPath"),
            self.TagRole: QByteArray(b"tag"),
            self.CategoryRole: QByteArray(b"category"),
            self.CategoryLabelRole: QByteArray(b"categoryLabel"),
            self.OriginalTextRole: QByteArray(b"originalText"),
            self.TranslatedTextRole: QByteArray(b"translatedText"),
            self.PrevContextRole: QByteArray(b"prevContext"),
            self.NextContextRole: QByteArray(b"nextContext"),
            self.IsModifiedRole: QByteArray(b"isModified"),
            self.LineCountRole: QByteArray(b"lineCount"),
            self.HasWarningRole: QByteArray(b"hasWarning"),
            self.WarningMsgRole: QByteArray(b"warningMsg"),
        }

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Replace model rows atomically."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def update_row_by_id(self, entry_id: int, updated_dict: dict[str, Any]) -> None:
        """Update a specific row in the model by primary ID."""
        for idx, row in enumerate(self._rows):
            if row.get("id") == entry_id:
                self._rows[idx] = dict(updated_dict)
                top_left = self.index(idx, 0)
                self.dataChanged.emit(top_left, top_left)
                break


class ScanWorker(QThread):
    """Background worker for non-blocking project scanning and database indexing."""

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(bool, str, int)

    def __init__(
        self,
        project_path: str,
        store: EditorStore,
        settings: dict[str, Any],
        force_rescan: bool = False,
    ) -> None:
        super().__init__()
        self.project_path = project_path
        self.store = store
        self.settings = settings
        self.force_rescan = force_rescan

    def run(self) -> None:
        try:
            from src.core.translation_pipeline import TranslationPipeline
            pipeline = TranslationPipeline(self.settings)

            self.progress.emit(0, 100, "Scanning files...")

            target_path = self.project_path
            if os.path.isfile(target_path):
                target_path = os.path.dirname(target_path)

            data_dir = pipeline._find_data_dir(target_path)
            if data_dir:
                files = pipeline._collect_files(data_dir)
            else:
                try:
                    files = pipeline._collect_files(target_path)
                except Exception:
                    files = []

            if not files:
                has_wolf_archive = False
                try:
                    search_dirs = [target_path]
                    if data_dir and os.path.isdir(data_dir):
                        search_dirs.append(data_dir)
                    for d in ("data", "Data"):
                        sub_d = os.path.join(target_path, d)
                        if os.path.isdir(sub_d) and sub_d not in search_dirs:
                            search_dirs.append(sub_d)

                    for sdir in search_dirs:
                        if os.path.isdir(sdir):
                            if any(f.lower().endswith(".wolf") for f in os.listdir(sdir)):
                                has_wolf_archive = True
                                break
                except Exception:
                    pass

                from src.backend.locale_manager import LocaleManager
                if has_wolf_archive:
                    msg = LocaleManager.get_text(
                        "status_encrypted_wolf",
                        default=(
                            "This WOLF RPG game contains packed/encrypted (.wolf) archives. "
                            "Please extract the archives into the 'Data' folder before translating.<br><br>"
                            "👉 <a href=\"https://github.com/Sinflower/UberWolf/releases\" style=\"color: #9d8dfc; text-decoration: underline;\">"
                            "Download the UberWolf tool here (GitHub)</a>"
                        ),
                    )
                else:
                    msg = LocaleManager.get_text(
                        "status_no_data",
                        default="No valid RPG Maker or WOLF RPG data folder found (.json, .rxdata, .mps, .dat, etc.).",
                    )

                self.finished.emit(False, msg, 0)
                return

            # Check if persistent cache is valid for instant load (<50ms)
            if not self.force_rescan and self.store.is_cache_valid(files):
                self.progress.emit(100, 100, "Loaded instantly from cache.")
                cur = self.store.conn.cursor()
                cur.execute("SELECT COUNT(*) FROM entries")
                total = cur.fetchone()[0]
                self.finished.emit(True, "Loaded from cache successfully.", total)
                return

            def on_extract_progress(curr: int, total: int, msg: str) -> None:
                pct = 15 + int((curr / max(total, 1)) * 55)
                self.progress.emit(pct, 100, msg)

            self.progress.emit(15, 100, f"Parsing {len(files)} files...")
            all_entries, parsed_files, _ = pipeline._extract_all_text(files, progress_callback=on_extract_progress)

            # Build extracted dict for store
            extracted_dict: dict[str, list[tuple[str, str, str]]] = {}
            for fp, (_parser, entries) in parsed_files.items():
                extracted_dict[fp] = entries

            # Attempt to resolve vanilla (pre-translation) text from the oldest backup
            # in each file's `.rpgm_backup/` folder — the same location the pipeline uses.
            backup_dict: dict[str, dict[str, str]] = {}
            backup_mgr = BackupManager()
            for fp in parsed_files:
                backups = backup_mgr.get_backups_for_file(fp)
                if not backups:
                    continue
                orig_entries = _extract_entries_from_backup(fp, backups[0], self.settings)
                if orig_entries:
                    backup_dict[fp] = {p: t for p, t, _ in orig_entries}

            self.progress.emit(70, 100, "Indexing database...")
            total_loaded = self.store.load_entries(
                extracted_dict,
                backup_files=backup_dict,
                cache_resolver=pipeline.cache,
                target_lang=self.settings.get("target_lang", "tr"),
                source_lang=self.settings.get("source_lang", "auto"),
            )

            self.progress.emit(100, 100, "Done!")
            self.finished.emit(True, f"{total_loaded} strings loaded successfully.", total_loaded)
        except Exception as exc:
            self.finished.emit(False, f"Scan error: {exc}", 0)



class AutoTranslateWorker(QThread):
    """Background worker that auto-translates untranslated editor entries.

    Accelerated with TextMerger to pack consecutive dialogues into high-throughput
    blocks and scoped to optional file, category, or search filters.
    """

    progress = pyqtSignal(int, int, str)   # (completed, total, status_msg)
    finished = pyqtSignal(int, str)        # (translated_count, message)
    pageApplied = pyqtSignal(int)          # (rows_written) - UI can refresh mid-run

    _BATCH_SIZE = 100  # entries fetched per page from DB
    _CANCEL_POLL_SECONDS = 0.2

    def __init__(
        self,
        store: "EditorStore",
        settings: dict,
        file_filter: str = "all",
        category_filter: str = "all",
        search_query: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.settings = settings
        self.file_filter = file_filter
        self.category_filter = category_filter
        self.search_query = search_query
        self._cancel = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def cancel(self) -> None:
        """Request cancellation. Any request in flight is aborted, not awaited."""
        self._cancel = True

    def _run_cancellable(self, loop, coro):
        """Await `coro`, abandoning it promptly if cancel() is called.

        A page of 100 lines is a single request that can take minutes on a local
        model. Checking the flag only between pages made the Cancel button look
        dead, so the request itself is cancelled instead. Returns None when the
        run was cancelled.
        """
        import asyncio

        async def runner():
            task = asyncio.ensure_future(coro)
            while not task.done():
                if self._cancel:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    return None
                await asyncio.sleep(self._CANCEL_POLL_SECONDS)
            try:
                return task.result()
            except asyncio.CancelledError:
                return None

        return loop.run_until_complete(runner())

    def run(self) -> None:  # noqa: C901
        import asyncio
        from src.core.translator import create_translator
        from src.core.translators.base import TranslationRequest
        from src.core.text_segmenter import SegmentType, clean_text, reassemble
        from src.core.text_merger import TextMerger
        from src.core.glossary import Glossary
        from src.core.translation_quality import translation_issues

        source_lang: str = self.settings.get("source_lang", "auto")
        target_lang: str = self.settings.get("target_lang", "tr")

        # Count total untranslated entries for the specific scope
        total_untranslated: int = self.store.get_untranslated_count(
            file_filter=self.file_filter,
            category_filter=self.category_filter,
            search_query=self.search_query,
        )
        if total_untranslated == 0:
            self.finished.emit(0, "No text found to translate.")
            return

        translator = create_translator(self.settings)
        glossary_path = self.settings.get("glossary_path", "")
        glossary = Glossary(glossary_path) if self.settings.get("use_glossary") and glossary_path and os.path.isfile(glossary_path) else None
        from src.core.translators.services import HyMT2Translator
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        completed = 0
        translated_count = 0
        last_id = 0

        # Run-wide memo of cleaned-source -> translation. The translator dedups
        # only inside a single call, and this worker pages 100 rows at a time,
        # so without this every repeat of "\u306f\u3044" / an item name in another file was
        # paid for again. RPG corpora are heavily repetitive, so this is the
        # single largest saving on a big project.
        seen_translations: dict[str, str] = {}
        cache_hits = 0
        memo_hits = 0

        translation_cache = None
        if self.settings.get("use_cache", True):
            try:
                from src.core.cache import get_cache
                translation_cache = get_cache(
                    cache_dir=get_cache_dir(get_project_id(self.settings.get("project_path", ""))),
                    project_id=get_project_id(self.settings.get("project_path", "")),
                    target_lang=target_lang,
                )
            except Exception as cache_exc:
                self.logger.warning("Translation cache unavailable: %s", cache_exc)

        try:
            if isinstance(translator, HyMT2Translator):
                loop.run_until_complete(translator.verify_connection())
            started_at = time.monotonic()
            while not self._cancel:
                batch = self.store.get_untranslated_batch(
                    last_id=last_id,
                    limit=self._BATCH_SIZE,
                    file_filter=self.file_filter,
                    category_filter=self.category_filter,
                    search_query=self.search_query,
                )
                if not batch:
                    break

                # Advance last_id to highest entry id in this batch
                last_id = max(entry["id"] for entry in batch)

                # Segment each entry and package through TextMerger
                segments_by_id: dict[int, list] = {}
                pairs: list[tuple[int, str]] = []
                merger = TextMerger(batch_size=1 if isinstance(translator, HyMT2Translator) else 15)

                clean_by_id: dict[int, str] = {}
                terms_by_id: dict[int, dict] = {}
                original_by_id: dict[int, str] = {}

                retry_ids: list[int] = []

                def _flush_pairs() -> None:
                    """Commit whatever is translated so far.

                    Called after the main pass, after the retry pass, and on
                    cancellation, so stopping a run never discards completed
                    lines. The store commits immediately, so the work survives
                    even if the app is closed straight afterwards.
                    """
                    nonlocal translated_count
                    if not pairs:
                        return
                    written = self.store.bulk_apply_auto_translations(list(pairs))
                    translated_count += len(pairs)
                    pairs.clear()
                    if written:
                        self.pageApplied.emit(written)

                def _apply(eid_raw: Any, translated: str, memoize: bool = True) -> None:
                    try:
                        eid = int(eid_raw)
                    except (ValueError, TypeError):
                        return
                    segs = segments_by_id.get(eid)
                    if any(token not in translated for token in terms_by_id.get(eid, {})):
                        return
                    restored = reassemble(translated, segs) if segs else translated
                    if glossary:
                        restored = glossary.restore_terms(restored, terms_by_id.get(eid, {}))
                    if translation_issues(original_by_id[eid], restored):
                        if eid not in retry_ids:
                            retry_ids.append(eid)
                        return
                    pairs.append((eid, restored))
                    if memoize:
                        # Key on the cleaned source so the next identical string
                        # anywhere in the project is free.
                        source_clean = clean_by_id.get(eid)
                        if source_clean:
                            seen_translations[source_clean] = translated
                            if translation_cache is not None:
                                translation_cache.set(
                                    source_clean, translated, source_lang, target_lang
                                )

                for entry in batch:
                    orig: str = entry["original_text"]
                    protected, term_map = glossary.protect_terms(orig) if glossary else (orig, {})
                    clean, segs = clean_text(protected)
                    has_translatable_text = any(
                        any(c.isalnum() for c in s.content)
                        for s in segs if s.type == SegmentType.TEXT
                    )
                    if not has_translatable_text:
                        # Code-only or pure punctuation string – nothing to translate, leave untouched
                        continue

                    segments_by_id[entry["id"]] = segs
                    clean_by_id[entry["id"]] = clean
                    terms_by_id[entry["id"]] = term_map
                    original_by_id[entry["id"]] = orig

                    # Already translated this exact string earlier in the run,
                    # or in an earlier run? Reuse it instead of paying again.
                    known = seen_translations.get(clean)
                    if known is not None:
                        memo_hits += 1
                        _apply(entry["id"], known, memoize=False)
                        continue
                    if translation_cache is not None:
                        cached = translation_cache.get(clean, source_lang, target_lang)
                        if cached:
                            cache_hits += 1
                            seen_translations[clean] = cached
                            _apply(entry["id"], cached, memoize=False)
                            continue

                    merger.add(
                        key=str(entry["id"]),
                        text=clean,
                        context_info=entry.get("tag", ""),
                    )

                merged_requests = merger.get_requests()
                if merged_requests:
                    batch_progress = 0

                    def on_item_done(count: int = 1) -> None:
                        nonlocal batch_progress
                        batch_progress += count
                        current = min(total_untranslated, completed + batch_progress)
                        elapsed = max(time.monotonic() - started_at, 0.001)
                        speed = current / elapsed
                        eta = int((total_untranslated - current) / speed) if speed > 0 else 0
                        minutes, seconds = divmod(eta, 60)
                        pct = min(100, int(current / total_untranslated * 100))
                        self.progress.emit(
                            pct, 100,
                            f"{current}/{total_untranslated} · {speed:.1f} strings/s · {minutes}m {seconds}s left",
                        )

                    req_objs = [
                        TranslationRequest(
                            text=req["text"],
                            source_lang=source_lang,
                            target_lang=target_lang,
                        )
                        for req in merged_requests
                    ]
                    results = self._run_cancellable(
                        loop,
                        translator.translate_batch(req_objs, progress_callback=on_item_done),
                    )
                    if results is None:
                        _flush_pairs()
                        break

                    for req, res in zip(merged_requests, results):
                        if not res.success or not res.translated_text:
                            continue
                        meta = req.get("metadata", {})
                        if meta.get("is_merged"):
                            original_entries = meta.get("original_entries", [])
                            split_results, mismatch = merger.split_merged_result_checked(
                                res.translated_text, original_entries
                            )
                            if mismatch:
                                # Separator lost/duplicated by the engine — a padded split
                                # would corrupt entries, so retry this block unmerged
                                # (same policy as TranslationPipeline).
                                for _ctx, key_str, _txt in original_entries:
                                    try:
                                        retry_ids.append(int(key_str))
                                    except (ValueError, TypeError):
                                        pass
                                continue
                            for key_str, split_text in split_results:
                                _apply(key_str, split_text)
                        else:
                            _apply(meta.get("key", 0), res.translated_text)

                    # Commit the main pass before spending time on retries.
                    _flush_pairs()

                if retry_ids and not self._cancel:
                    retry_reqs = [
                        TranslationRequest(
                            text=clean_by_id[eid],
                            source_lang=source_lang,
                            target_lang=target_lang,
                        )
                        for eid in retry_ids if eid in clean_by_id
                    ]
                    retry_results = self._run_cancellable(
                        loop, translator.translate_batch(retry_reqs)
                    )
                    if retry_results is None:
                        _flush_pairs()
                        break
                    for eid, res in zip([e for e in retry_ids if e in clean_by_id], retry_results):
                        if res.success and res.translated_text:
                            _apply(eid, res.translated_text)

                _flush_pairs()

                completed += len(batch)
                pct = min(100, int(completed / max(total_untranslated, 1) * 100))
                self.progress.emit(
                    pct, 100,
                    f"{completed}/{total_untranslated} · {completed / max(time.monotonic() - started_at, 0.001):.1f} strings/s",
                )

        except Exception as exc:
            self.finished.emit(translated_count, f"Auto-translation error: {exc}")
            return
        finally:
            loop.run_until_complete(translator.close())
            loop.close()
            if translation_cache is not None:
                try:
                    translation_cache.save()
                except Exception as save_exc:
                    self.logger.warning("Could not persist translation cache: %s", save_exc)
            reused = memo_hits + cache_hits
            if reused:
                self.logger.info(
                    "Auto-translate reused %d strings without a request "
                    "(%d repeats within this run, %d from the cache).",
                    reused, memo_hits, cache_hits,
                )

        if self._cancel:
            self.finished.emit(
                translated_count,
                f"Cancelled - {translated_count} strings translated and saved.",
            )
        else:
            self.finished.emit(translated_count, f"Done! {translated_count} strings translated successfully.")


#: Engines offered in the editor's right-click "Translate with" menu. Order is
#: the order shown. The `id` must match a case in translators.manager.create_translator.
#: DeepL needs no separate free entry: DeepLTranslator picks api-free.deepl.com
#: automatically when the key carries the ":fx" suffix that free keys have.
SINGLE_TRANSLATE_ENGINES: list[dict[str, str]] = [
    {"id": "", "name": "Current engine", "needs_key": ""},
    {"id": "local_llm", "name": "\U0001F999 Local LLM", "needs_key": ""},
    {"id": "hy_mt2", "name": "\U0001F238 Hy-MT2 (Local)", "needs_key": ""},
    {"id": "openai", "name": "\U0001F916 OpenAI", "needs_key": "openai_api_key",
     "setup_url": "https://platform.openai.com/api-keys"},
    {"id": "deepseek", "name": "\U0001F30A DeepSeek", "needs_key": "deepseek_api_key",
     "setup_url": "https://platform.deepseek.com/api_keys"},
    {"id": "gemini", "name": "\u2728 Google Gemini", "needs_key": "gemini_api_key",
     "setup_url": "https://aistudio.google.com/app/apikey"},
    {"id": "deepl", "name": "\U0001F3AF DeepL (Free or Pro)", "needs_key": "deepl_api_key",
     "setup_url": "https://www.deepl.com/pro-api"},
    {"id": "libretranslate", "name": "\U0001F513 LibreTranslate", "needs_key": ""},
    {"id": "google", "name": "\U0001F310 Google Translate (free)", "needs_key": ""},
]


class SingleTranslateWorker(QThread):
    """Translate one entry with a chosen engine, off the UI thread.

    Mirrors AutoTranslateWorker's protect -> clean -> translate -> reassemble
    chain so a one-off translation is guarded exactly like a bulk one; the only
    difference is that the engine can be overridden per call.
    """

    finished = pyqtSignal(int, bool, str)  # (entry_id, success, message)

    def __init__(
        self,
        store: "EditorStore",
        settings: dict,
        entry_id: int,
        engine: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.settings = dict(settings)
        if engine:
            self.settings["engine"] = engine
        self.entry_id = entry_id
        self.engine = engine or str(settings.get("engine", "google"))
        self.result_text: str = ""
        self.logger = logging.getLogger(self.__class__.__name__)

    def run(self) -> None:
        import asyncio
        from src.core.translator import create_translator
        from src.core.translators.base import TranslationRequest
        from src.core.text_segmenter import clean_text, reassemble
        from src.core.glossary import Glossary

        row = self.store.get_entry(self.entry_id)
        if not row:
            self.finished.emit(self.entry_id, False, "Entry not found.")
            return

        original = row.get("original_text", "")
        if not original.strip():
            self.finished.emit(self.entry_id, False, "Nothing to translate.")
            return

        source_lang = self.settings.get("source_lang", "auto")
        target_lang = self.settings.get("target_lang", "en")

        glossary_path = self.settings.get("glossary_path", "")
        glossary = (
            Glossary(glossary_path)
            if self.settings.get("use_glossary") and glossary_path and os.path.isfile(glossary_path)
            else None
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        translator = None
        try:
            translator = create_translator(self.settings)
            protected, term_map = glossary.protect_terms(original) if glossary else (original, {})
            clean, segs = clean_text(protected)
            if not clean.strip():
                self.finished.emit(self.entry_id, False, "Nothing translatable in this entry.")
                return

            results = loop.run_until_complete(
                translator.translate_batch([
                    TranslationRequest(
                        text=clean, source_lang=source_lang, target_lang=target_lang
                    )
                ])
            )
            if not results or not results[0].success or not results[0].translated_text:
                err = (results[0].error if results else None) or "no text returned"
                self.finished.emit(self.entry_id, False, f"{self.engine}: {err}")
                return

            translated = results[0].translated_text
            restored = reassemble(translated, segs) if segs else translated
            if glossary:
                restored = glossary.restore_terms(restored, term_map)
            self.result_text = restored
            self.finished.emit(self.entry_id, True, self.engine)
        except Exception as exc:
            self.logger.warning("Single translate failed (%s): %s", self.engine, exc)
            self.finished.emit(self.entry_id, False, f"{self.engine}: {exc}")
        finally:
            try:
                if translator is not None:
                    loop.run_until_complete(translator.close())
            except Exception:
                pass
            loop.close()


class EditorBackend(QObject):
    """Main controller for the in-app translation editor tab."""

    projectLoadedChanged = pyqtSignal()
    isScanningChanged = pyqtSignal()
    scanProgressChanged = pyqtSignal(int, int, str)
    scanStatusMessageChanged = pyqtSignal()
    filtersChanged = pyqtSignal()
    statsChanged = pyqtSignal()
    selectedEntryChanged = pyqtSignal()
    hasUnsavedChangesChanged = pyqtSignal()
    saveFinished = pyqtSignal(bool, str)
    batchReplaceFinished = pyqtSignal(int, str)
    autoTranslateProgressChanged = pyqtSignal()
    autoTranslateFinished = pyqtSignal(bool, str)   # (success, message)
    scanFinished = pyqtSignal(bool, str, int)       # (success, message, count)
    singleTranslateFinished = pyqtSignal(int, bool, str)  # (entryId, success, message)
    singleTranslateRunningChanged = pyqtSignal()

    def __init__(
        self,
        app_backend: Any,
        settings_backend: Any,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.app_backend = app_backend
        self.settings_backend = settings_backend

        self._table_model = EditorTableModel(self)
        self._single_worker: SingleTranslateWorker | None = None
        self._store: EditorStore | None = None
        self._scan_worker: ScanWorker | None = None
        self._auto_translate_worker: AutoTranslateWorker | None = None

        self._is_auto_translating: bool = False
        self._auto_translate_progress: int = 0
        self._auto_translate_status: str = ""

        self._project_loaded: bool = False
        self._scan_attempted: bool = False
        self._is_scanning: bool = False
        self._scan_progress_current: int = 0
        self._scan_progress_total: int = 100
        self._scan_progress_text: str = ""
        self._scan_status_message: str = ""

        # Filters and search state
        self._search_query: str = ""
        self._selected_category: str = "all"
        self._selected_file: str = "all"
        self._selected_status: str = "all"

        # Pagination state
        self._current_page: int = 1
        self._page_size: int = 50
        self._total_count: int = 0
        self._total_pages: int = 1

        # Stats
        self._total_project_count: int = 0
        self._modified_count: int = 0
        self._warning_count: int = 0
        self._untranslated_count: int = 0

        # Detail selection
        self._selected_entry_id: int = 0
        self._selected_entry: dict[str, Any] = {}

        # Concurrency safety hooks
        if hasattr(self.app_backend, "projectPathChanged"):
            self.app_backend.projectPathChanged.connect(self._on_project_path_changed)
        if hasattr(self.app_backend, "finished"):
            self.app_backend.finished.connect(self._on_pipeline_finished)
        if hasattr(self.app_backend, "cacheAboutToBeCleared"):
            self.app_backend.cacheAboutToBeCleared.connect(self._on_cache_about_to_be_cleared)
        self.app_backend.editor_backend = self

    # --- Properties ---

    @pyqtProperty(QObject, constant=True)
    def tableModel(self) -> EditorTableModel:
        return self._table_model

    @pyqtProperty(bool, notify=projectLoadedChanged)
    def projectLoaded(self) -> bool:
        return self._project_loaded

    @pyqtProperty(bool, notify=projectLoadedChanged)
    def scanAttempted(self) -> bool:
        return self._scan_attempted

    @pyqtProperty(bool, notify=isScanningChanged)
    def isScanning(self) -> bool:
        return self._is_scanning

    @pyqtProperty(int, notify=scanProgressChanged)
    def scanProgressCurrent(self) -> int:
        return self._scan_progress_current

    @pyqtProperty(int, notify=scanProgressChanged)
    def scanProgressTotal(self) -> int:
        return self._scan_progress_total

    @pyqtProperty(str, notify=scanProgressChanged)
    def scanProgressText(self) -> str:
        return self._scan_progress_text

    @pyqtProperty(str, notify=filtersChanged)
    def searchQuery(self) -> str:
        return self._search_query

    @pyqtProperty(str, notify=filtersChanged)
    def selectedCategory(self) -> str:
        return self._selected_category

    @pyqtProperty(str, notify=filtersChanged)
    def selectedFile(self) -> str:
        return self._selected_file

    @pyqtProperty(str, notify=filtersChanged)
    def selectedStatus(self) -> str:
        return self._selected_status

    @pyqtProperty(int, notify=filtersChanged)
    def currentPage(self) -> int:
        return self._current_page

    @pyqtProperty(int, notify=filtersChanged)
    def pageSize(self) -> int:
        return self._page_size

    @pyqtProperty(int, notify=filtersChanged)
    def totalCount(self) -> int:
        return self._total_count

    @pyqtProperty(int, notify=filtersChanged)
    def totalPages(self) -> int:
        return self._total_pages

    @pyqtProperty(int, notify=statsChanged)
    def modifiedCount(self) -> int:
        return self._modified_count

    @pyqtProperty(int, notify=statsChanged)
    def warningCount(self) -> int:
        return self._warning_count

    @pyqtProperty(int, notify=statsChanged)
    def untranslatedCount(self) -> int:
        return self._untranslated_count

    @pyqtProperty(bool, notify=hasUnsavedChangesChanged)
    def hasUnsavedChanges(self) -> bool:
        return self._modified_count > 0

    @pyqtProperty("QVariantMap", notify=selectedEntryChanged)
    def selectedEntry(self) -> dict[str, Any]:
        return self._selected_entry

    @pyqtProperty("QVariantList", notify=projectLoadedChanged)
    def categories(self) -> list[dict[str, str]]:
        """Return category chips for UI filtering."""
        return [
            {"key": k, "label": v}
            for k, v in CATEGORY_LABELS.items()
        ]

    @pyqtProperty("QVariantList", notify=filtersChanged)
    def fileList(self) -> list[str]:
        """Return available files scoped to the currently selected category."""
        if not self._store:
            return [ALL_FILES_LABEL]

        cat_map = self._store.get_categories_and_files()
        if self._selected_category == "all":
            all_files = sorted({fn for files in cat_map.values() for fn in files})
            return [ALL_FILES_LABEL] + all_files

        cat_files = cat_map.get(self._selected_category, [])
        return [ALL_FILES_LABEL] + cat_files

    @pyqtProperty(str, notify=filtersChanged)
    def activeFileFilter(self) -> str:
        return self._selected_file

    @pyqtProperty(str, notify=filtersChanged)
    def activeCategoryFilter(self) -> str:
        return self._selected_category

    @pyqtProperty(str, notify=filtersChanged)
    def activeSearchQuery(self) -> str:
        return self._search_query

    @pyqtProperty(str, notify=projectLoadedChanged)
    def projectPath(self) -> str:
        return getattr(self.app_backend, "projectPath", "")

    @pyqtProperty(str, notify=projectLoadedChanged)
    def projectName(self) -> str:
        path = getattr(self.app_backend, "projectPath", "")
        if not path:
            return ""
        return os.path.basename(os.path.normpath(path))

    @pyqtProperty(int, notify=statsChanged)
    def totalProjectCount(self) -> int:
        return self._total_project_count

    @pyqtProperty(str, notify=scanStatusMessageChanged)
    def scanStatusMessage(self) -> str:
        return self._scan_status_message

    @pyqtProperty(bool, notify=autoTranslateProgressChanged)
    def isAutoTranslating(self) -> bool:
        return self._is_auto_translating

    @pyqtProperty(int, notify=autoTranslateProgressChanged)
    def autoTranslateProgress(self) -> int:
        return self._auto_translate_progress

    @pyqtProperty(str, notify=autoTranslateProgressChanged)
    def autoTranslateStatus(self) -> str:
        return self._auto_translate_status

    # --- Slots ---

    @pyqtSlot(result=str)
    def selectGameFolder(self) -> str:
        """Open native directory dialog to select RPG Maker game directory."""
        from PyQt6.QtWidgets import QFileDialog
        current_path = getattr(self.app_backend, "projectPath", "")
        folder = QFileDialog.getExistingDirectory(
            None, "Select RPG Maker Game Folder", current_path or ""
        )
        if folder:
            self.setProjectPath(folder)
            return folder
        return ""

    @pyqtSlot(str)
    def setProjectPath(self, path: str) -> None:
        """Select a folder in the editor and load it on this explicit action."""
        if not path:
            return
        cleaned = os.path.normpath(local_path_from_url(path))
        if os.path.isfile(cleaned):
            cleaned = os.path.dirname(cleaned)

        current_path = getattr(self.app_backend, "projectPath", "")
        if current_path == cleaned:
            self.loadProject(force_rescan=False)
        else:
            if hasattr(self.app_backend, "setProjectPath"):
                self.app_backend.setProjectPath(cleaned)
            elif hasattr(self.app_backend, "projectPath"):
                self.app_backend.projectPath = cleaned
            self.loadProject(force_rescan=False)

    @pyqtSlot()
    def closeStore(self) -> None:
        """Release the active SQLite store, abort workers, and reset table model."""
        self._on_cache_about_to_be_cleared()

    def _on_cache_about_to_be_cleared(self) -> None:
        """Release SQLite store, abort background workers, and clear table rows prior to cache deletion."""
        self.logger.info("Releasing editor store and background workers for cache clearing")
        if self._scan_worker and self._scan_worker.isRunning():
            self._scan_worker.terminate()
            self._scan_worker.wait(1000)
            self._scan_worker = None
        if self._auto_translate_worker and self._auto_translate_worker.isRunning():
            self._auto_translate_worker.cancel()
            self._auto_translate_worker.wait(1000)
            self._auto_translate_worker = None

        if self._store:
            try:
                self._store.close()
            except Exception as exc:
                self.logger.warning(f"Error closing EditorStore: {exc}")
            finally:
                self._store = None

        self._project_loaded = False
        self._scan_attempted = False
        self._table_model.set_rows([])
        self._set_selected_entry_dict({})
        self._total_project_count = 0
        self._modified_count = 0
        self._warning_count = 0
        self._untranslated_count = 0
        self.statsChanged.emit()
        self.hasUnsavedChangesChanged.emit()
        self.projectLoadedChanged.emit()
        self.isScanningChanged.emit()

    @pyqtSlot()
    def scanOrLoadProject(self) -> None:
        """Trigger project scan or load using current appBackend project path."""
        self.loadProject(force_rescan=False)

    @pyqtSlot(bool)
    def loadProject(self, force_rescan: bool = False) -> None:
        """Load or rescan strings for the current active project path."""
        project_path = getattr(self.app_backend, "projectPath", "")
        if not project_path or not os.path.exists(project_path):
            return

        if self._is_scanning:
            return

        self._scan_attempted = True
        self.projectLoadedChanged.emit()

        project_id = get_project_id(project_path)
        db_dir = get_cache_dir(project_id)
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, "editor_strings.db")

        if self._store:
            self._store.close()
        self._store = EditorStore(db_path)

        self._is_scanning = True
        self.isScanningChanged.emit()

        settings = self.settings_backend.get_dict() if hasattr(self.settings_backend, "get_dict") else {}
        self._scan_worker = ScanWorker(project_path, self._store, settings, force_rescan=force_rescan)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.start()

    def _on_scan_progress(self, curr: int, total: int, msg: str) -> None:
        self._scan_progress_current = curr
        self._scan_progress_total = total
        self._scan_progress_text = msg
        self.scanProgressChanged.emit(curr, total, msg)

    def _on_scan_finished(self, success: bool, msg: str, count: int) -> None:
        self._is_scanning = False
        self.isScanningChanged.emit()
        self._scan_status_message = msg
        self.scanStatusMessageChanged.emit()

        if success:
            self._project_loaded = True
            self.projectLoadedChanged.emit()
            self._current_page = 1
            self._refresh_page()
            self._refresh_stats()
            self.logger.info(f"Editor loaded {count} strings successfully.")
        else:
            self._project_loaded = False
            self.projectLoadedChanged.emit()
            self._table_model.set_rows([])
            self._total_count = 0
            self._total_project_count = 0
            self._refresh_stats()
            self.logger.warning(f"Editor scan failed: {msg}")

        self.scanFinished.emit(success, msg, count)

    def _refresh_page(self) -> None:
        """Fetch current page rows from store and update table model."""
        if not self._store:
            return

        file_filt = "all" if self._selected_file in ALL_FILES_ALIASES else self._selected_file
        rows, total = self._store.query_page(
            search_query=self._search_query,
            category_filter=self._selected_category,
            file_filter=file_filt,
            status_filter=self._selected_status,
            page=self._current_page,
            page_size=self._page_size,
        )

        self._total_count = total
        self._total_pages = max(1, (total + self._page_size - 1) // self._page_size)

        if self._current_page > self._total_pages:
            self._current_page = self._total_pages
            rows, _ = self._store.query_page(
                search_query=self._search_query,
                category_filter=self._selected_category,
                file_filter=file_filt,
                status_filter=self._selected_status,
                page=self._current_page,
                page_size=self._page_size,
            )

        self._table_model.set_rows(rows)
        self.filtersChanged.emit()

        # If previously selected row is in new rows, refresh selection
        if self._selected_entry_id > 0:
            matching = [r for r in rows if r["id"] == self._selected_entry_id]
            if matching:
                self._set_selected_entry_dict(matching[0])
            elif rows:
                self._set_selected_entry_dict(rows[0])
            else:
                self._set_selected_entry_dict({})
        elif rows:
            self._set_selected_entry_dict(rows[0])

    def _refresh_stats(self) -> None:
        """Update statistical counters from store."""
        if not self._store:
            self._total_project_count = 0
            self._modified_count = 0
            self._warning_count = 0
            self._untranslated_count = 0
            self.statsChanged.emit()
            self.hasUnsavedChangesChanged.emit()
            return
        stats = self._store.get_stats()
        self._total_project_count = stats.get("total", 0)
        self._modified_count = stats.get("modified", 0)
        self._warning_count = stats.get("warnings", 0)
        self._untranslated_count = stats.get("untranslated", 0)
        self.statsChanged.emit()
        self.hasUnsavedChangesChanged.emit()

    def _set_selected_entry_dict(self, entry: dict[str, Any]) -> None:
        """Extract codes and set entry payload for the detail editor."""
        if entry:
            self._selected_entry_id = entry.get("id", 0)
            entry_copy = dict(entry)
            orig = entry.get("original_text", "")
            codes = extract_escape_codes(orig)
            entry_copy["escape_codes"] = list(dict.fromkeys(codes))  # unique preserving order
            self._selected_entry = entry_copy
        else:
            self._selected_entry_id = 0
            self._selected_entry = {}
        self.selectedEntryChanged.emit()

    @pyqtSlot(str)
    def setSearchQuery(self, val: str) -> None:
        if self._search_query != val:
            self._search_query = val
            self._current_page = 1
            self._refresh_page()

    @pyqtSlot(str)
    def setSelectedCategory(self, val: str) -> None:
        if self._selected_category != val:
            self._selected_category = val
            self._selected_file = "all"  # reset file filter on category change
            self._current_page = 1
            self._refresh_page()

    @pyqtSlot(str)
    def setSelectedFile(self, val: str) -> None:
        actual_val = "all" if val in ALL_FILES_ALIASES else val
        if self._selected_file != actual_val:
            self._selected_file = actual_val
            self._current_page = 1
            self._refresh_page()

    @pyqtSlot(str)
    def setSelectedStatus(self, val: str) -> None:
        if self._selected_status != val:
            self._selected_status = val
            self._current_page = 1
            self._refresh_page()

    @pyqtSlot(int)
    def setPage(self, page: int) -> None:
        p = max(1, min(page, self._total_pages))
        if self._current_page != p:
            self._current_page = p
            self._refresh_page()

    @pyqtSlot(int)
    def setPageSize(self, size: int) -> None:
        s = max(10, min(size, 500))
        if self._page_size != s:
            self._page_size = s
            self._current_page = 1
            self._refresh_page()

    @pyqtSlot(int)
    def selectEntryById(self, entry_id: int) -> None:
        if not self._store or entry_id <= 0:
            return
        row = self._store.get_entry(entry_id)
        if row:
            self._set_selected_entry_dict(row)

    @pyqtSlot(str)
    def updateSelectedTranslation(self, new_text: str) -> None:
        """Update translation for the currently selected detail item."""
        if not self._store or self._selected_entry_id <= 0:
            return
        updated = self._store.update_entry(self._selected_entry_id, new_text)
        if updated:
            self._set_selected_entry_dict(updated)
            self._table_model.update_row_by_id(self._selected_entry_id, updated)
            self._refresh_stats()

    @pyqtProperty("QVariantList", constant=True)
    def singleTranslateEngines(self) -> list:
        """Engine choices for the editor's right-click menu.

        An engine whose credential is missing is still listed but marked
        unavailable, so the menu explains itself rather than silently failing.
        """
        out = []
        for spec in SINGLE_TRANSLATE_ENGINES:
            key_name = spec.get("needs_key") or ""
            available = True
            if key_name:
                try:
                    available = bool(str(self.settings_backend.get_dict().get(key_name, "")).strip())
                except Exception:
                    available = False
            out.append({
                "id": spec["id"],
                "name": spec["name"],
                "available": available,
                "needsKey": bool(key_name),
                "settingKey": key_name,
                "setupUrl": spec.get("setup_url", ""),
            })
        return out

    @pyqtProperty(bool, notify=singleTranslateRunningChanged)
    def singleTranslateRunning(self) -> bool:
        return self._single_worker is not None and self._single_worker.isRunning()

    @pyqtSlot(int, str)
    def translateEntryWith(self, entry_id: int, engine: str = "") -> None:
        """Translate one entry using a specific engine, leaving settings untouched."""
        if not self._store or entry_id <= 0:
            return
        if self._single_worker is not None and self._single_worker.isRunning():
            self.singleTranslateFinished.emit(
                entry_id, False, "Another single translation is still running."
            )
            return

        settings = self.settings_backend.get_dict()
        self._single_worker = SingleTranslateWorker(self._store, settings, entry_id, engine, self)
        self._single_worker.finished.connect(self._on_single_translate_finished)
        self._single_worker.start()
        self.singleTranslateRunningChanged.emit()

    def _on_single_translate_finished(self, entry_id: int, ok: bool, message: str) -> None:
        worker = self._single_worker
        if ok and worker is not None and worker.result_text:
            updated = self._store.update_entry(entry_id, worker.result_text)
            if updated:
                self._table_model.update_row_by_id(entry_id, updated)
                if entry_id == self._selected_entry_id:
                    self._set_selected_entry_dict(updated)
                self._refresh_stats()
                self.hasUnsavedChangesChanged.emit()
        self._single_worker = None
        self.singleTranslateRunningChanged.emit()
        self.singleTranslateFinished.emit(entry_id, ok, message)

    def _clean_source_for(self, entry_id: int) -> tuple[str, Any]:
        """Return (clean_text, segments) for an entry, or ("", None)."""
        from src.core.text_segmenter import clean_text
        from src.core.glossary import Glossary

        row = self._store.get_entry(entry_id) if self._store else None
        if not row:
            return "", None
        original = row.get("original_text", "")
        if not original.strip():
            return "", None

        settings = self.settings_backend.get_dict()
        glossary_path = settings.get("glossary_path", "")
        glossary = (
            Glossary(glossary_path)
            if settings.get("use_glossary") and glossary_path and os.path.isfile(glossary_path)
            else None
        )
        protected, term_map = glossary.protect_terms(original) if glossary else (original, {})
        clean, segs = clean_text(protected)
        return clean, (segs, term_map, glossary)

    @pyqtSlot(int, result="QVariantMap")
    def pasteTranslationForEntry(self, entry_id: int) -> dict:
        """Take the clipboard as this entry's translation, guarded like any engine.

        Runs the same reassemble + glossary-restore chain the translators use,
        so a hand-pasted translation cannot drop escape codes that a manual
        copy-paste into the grid would have lost.
        """
        from src.core.text_segmenter import reassemble

        if not self._store or entry_id <= 0:
            return {"ok": False, "message": "No entry selected.", "nextId": -1}
        try:
            from PyQt6.QtGui import QGuiApplication
            pasted = (QGuiApplication.clipboard().text() or "").strip()
        except Exception as exc:
            return {"ok": False, "message": f"Clipboard unavailable: {exc}", "nextId": -1}
        if not pasted:
            return {"ok": False, "message": "Clipboard is empty.", "nextId": -1}

        clean, bundle = self._clean_source_for(entry_id)
        if bundle is None:
            return {"ok": False, "message": "Entry not found.", "nextId": -1}
        segs, term_map, glossary = bundle

        if pasted == clean:
            return {"ok": False, "message": "Clipboard still holds the source text.", "nextId": -1}

        restored = reassemble(pasted, segs) if segs else pasted
        if glossary:
            restored = glossary.restore_terms(restored, term_map)

        updated = self._store.update_entry(entry_id, restored)
        if not updated:
            return {"ok": False, "message": "Could not update the entry.", "nextId": -1}

        self._table_model.update_row_by_id(entry_id, updated)
        if entry_id == self._selected_entry_id:
            self._set_selected_entry_dict(updated)
        self._refresh_stats()
        self.hasUnsavedChangesChanged.emit()

        issues = []
        try:
            from src.core.translation_quality import translation_issues
            issues = translation_issues(updated.get("original_text", ""), restored)
        except Exception:
            pass

        message = "Pasted." if not issues else "Pasted - check: " + ", ".join(issues)
        return {"ok": True, "message": message, "nextId": self.nextUntranslatedAfter(entry_id)}

    @pyqtSlot(int, result=int)
    def nextUntranslatedAfter(self, entry_id: int) -> int:
        """Id of the next still-untranslated entry in the current scope, or -1."""
        if not self._store:
            return -1
        rows = self._store.get_untranslated_batch(
            last_id=max(0, entry_id),
            limit=1,
            file_filter="all" if self._selected_file in ALL_FILES_ALIASES else self._selected_file,
            category_filter=self._selected_category,
            search_query=self._search_query,
        )
        return int(rows[0]["id"]) if rows else -1

    @pyqtSlot(str, result=str)
    def apiKeySetupUrl(self, engine: str) -> str:
        """Where a user obtains a key for this engine, for the browser hand-off."""
        for spec in SINGLE_TRANSLATE_ENGINES:
            if spec["id"] == engine:
                return str(spec.get("setup_url", ""))
        return ""

    @pyqtSlot(str, result=str)
    def clipboardApiKeyCandidate(self, engine: str) -> str:
        """Return the clipboard contents if they plausibly look like a key.

        Keys cannot be fetched programmatically - every provider puts account
        creation behind a login, and DeepL additionally requires card details
        for identity verification - so the best we can do is pre-fill what the
        user just copied and let them confirm it.
        """
        try:
            from PyQt6.QtGui import QGuiApplication
            text = (QGuiApplication.clipboard().text() or "").strip()
        except Exception:
            return ""
        if not text or len(text) > 200 or "\n" in text or " " in text:
            return ""
        if len(text) < 16:
            return ""
        return text

    @pyqtSlot(str, str, result="QVariantMap")
    def saveApiKeyFor(self, engine: str, key: str) -> dict:
        """Store a user-supplied key against the right provider setting."""
        key = (key or "").strip()
        spec = next((e for e in SINGLE_TRANSLATE_ENGINES if e["id"] == engine), None)
        if spec is None or not spec.get("needs_key"):
            return {"ok": False, "message": "This engine does not use an API key."}
        if not key:
            return {"ok": False, "message": "No key entered."}

        if engine == "deepl" and ":fx" not in key and len(key.split("-")) < 4:
            return {
                "ok": False,
                "message": "That does not look like a DeepL key. Free keys end in ':fx'.",
            }

        try:
            self.settings_backend._set(spec["needs_key"], key)
            self.settings_backend.save()
        except Exception as exc:
            return {"ok": False, "message": f"Could not save the key: {exc}"}
        return {"ok": True, "message": "Key saved."}

    @pyqtSlot()
    def revertSelectedEntry(self) -> None:
        """Revert currently selected translation to original text."""
        if not self._store or self._selected_entry_id <= 0:
            return
        reverted = self._store.revert_entry(self._selected_entry_id)
        if reverted:
            self._set_selected_entry_dict(reverted)
            self._table_model.update_row_by_id(self._selected_entry_id, reverted)
            self._refresh_stats()

    @pyqtSlot(str, str, str, str, bool)
    def batchReplace(
        self,
        search_term: str,
        replace_term: str,
        file_filter: str = "all",
        category_filter: str = "all",
        match_case: bool = False,
    ) -> None:
        """Perform escape-code safe batch replacement across translations."""
        if not self._store or not search_term:
            self.batchReplaceFinished.emit(0, "Search term cannot be empty.")
            return

        filt_f = "all" if file_filter in ALL_FILES_ALIASES else file_filter
        count = self._store.batch_replace(
            search_term,
            replace_term,
            file_filter=filt_f,
            category_filter=category_filter,
            match_case=match_case,
        )

        self._refresh_page()
        self._refresh_stats()
        msg = f"{count} strings updated safely." if count > 0 else "No matches found to replace."
        self.batchReplaceFinished.emit(count, msg)

    @pyqtSlot(str, result=int)
    def getScopeUntranslatedCount(self, scope: str) -> int:
        """Return untranslated entry count for the specified scope ('all', 'file', 'category', 'filtered')."""
        if not self._store:
            return 0
        if scope == "file":
            return self._store.get_untranslated_count(file_filter=self._selected_file)
        elif scope == "category":
            return self._store.get_untranslated_count(category_filter=self._selected_category)
        elif scope == "filtered":
            return self._store.get_untranslated_count(
                file_filter=self._selected_file,
                category_filter=self._selected_category,
                search_query=self._search_query,
            )
        return self._store.get_untranslated_count()

    @pyqtSlot()
    def startAutoTranslate(
        self,
        file_filter: str = "all",
        category_filter: str = "all",
        search_query: str = "",
    ) -> None:
        """Launch AutoTranslateWorker to translate untranslated strings in the editor database."""
        if not self._store or not self._project_loaded:
            self.autoTranslateFinished.emit(False, "Project has not been scanned yet.")
            return
        if self._is_auto_translating or self._is_scanning:
            return

        self._is_auto_translating = True
        self._auto_translate_progress = 0
        self._auto_translate_status = "Starting…"
        self.autoTranslateProgressChanged.emit()

        settings = self.settings_backend.get_dict() if hasattr(self.settings_backend, "get_dict") else {}
        self._auto_translate_worker = AutoTranslateWorker(
            self._store,
            settings,
            file_filter=file_filter,
            category_filter=category_filter,
            search_query=search_query,
            parent=self,
        )
        self._auto_translate_worker.progress.connect(self._on_auto_translate_progress)
        self._auto_translate_worker.pageApplied.connect(self._on_auto_translate_page_applied)
        self._auto_translate_worker.finished.connect(self._on_auto_translate_finished)
        self._auto_translate_worker.start()

    @pyqtSlot("QVariantMap")
    def startAutoTranslateWithOptions(self, options: dict[str, Any]) -> None:
        """Apply custom translation options, persist engine config, and start scoped auto-translation."""
        if options and hasattr(self.settings_backend, "_data"):
            for k, v in options.items():
                if v is not None and str(v).strip() and k not in ("scope", "scope_file", "scope_category", "scope_search"):
                    self.settings_backend._data[k] = v
            if hasattr(self.settings_backend, "save"):
                self.settings_backend.save()
            if hasattr(self.settings_backend, "settingsChanged"):
                self.settings_backend.settingsChanged.emit()

        scope = options.get("scope", "all") if options else "all"
        f_filter = "all"
        c_filter = "all"
        s_query = ""

        if scope == "file":
            f_filter = self._selected_file
        elif scope == "category":
            c_filter = self._selected_category
        elif scope == "filtered":
            f_filter = self._selected_file
            c_filter = self._selected_category
            s_query = self._search_query

        self.startAutoTranslate(file_filter=f_filter, category_filter=c_filter, search_query=s_query)

    @pyqtSlot()
    def cancelAutoTranslate(self) -> None:
        """Request graceful cancellation of the running auto-translate job."""
        if self._auto_translate_worker and self._auto_translate_worker.isRunning():
            self._auto_translate_worker.cancel()

    def _on_auto_translate_page_applied(self, _rows: int) -> None:
        """Refresh the grid as each page lands, so progress is visible mid-run.

        The rows were already committed by the worker; this only re-reads them
        so the user can watch the table fill instead of staring at a bar.
        """
        self._refresh_page()
        self._refresh_stats()
        self.hasUnsavedChangesChanged.emit()

    def _on_auto_translate_progress(self, pct: int, _total: int, msg: str) -> None:
        self._auto_translate_progress = pct
        self._auto_translate_status = msg
        self.autoTranslateProgressChanged.emit()

    def _on_auto_translate_finished(self, count: int, msg: str) -> None:
        self._is_auto_translating = False
        self._auto_translate_progress = 100 if count > 0 else 0
        self._auto_translate_status = msg
        self.autoTranslateProgressChanged.emit()

        success = count > 0 or "No matches found" in msg
        self.autoTranslateFinished.emit(success, msg)

        if count > 0:
            self._refresh_page()
            self._refresh_stats()

        self._auto_translate_worker = None

    @pyqtSlot()
    def saveChanges(self) -> None:
        """Surgically save modified files, take atomic backups, and update translation cache."""
        if not self._store or self._modified_count == 0:
            self.saveFinished.emit(True, "No changes to save.")
            return

        changes_by_file, originals_by_file = self._store.get_modified_entries()
        if not changes_by_file:
            self.saveFinished.emit(True, "No changes to save.")
            return

        settings = self.settings_backend.get_dict() if hasattr(self.settings_backend, "get_dict") else {}
        target_lang = settings.get("target_lang", "tr")
        source_lang = settings.get("source_lang", "auto")

        from src.core.translation_pipeline import TranslationPipeline
        pipeline = TranslationPipeline(settings)
        # Default backup dir (.rpgm_backup next to each file) — never the game folder itself.
        backup_mgr = BackupManager()
        saved_files: list[str] = []

        try:
            for fp, changes in changes_by_file.items():
                if not os.path.exists(fp):
                    continue

                file_ext = os.path.splitext(fp)[1].lower()
                from src.core.parser_factory import get_parser
                parser = get_parser(fp, settings)
                if not parser:
                    continue

                # 1. Take atomic backup
                backup_mgr.create_backup(fp)

                try:
                    # 2. Apply translation using parser
                    new_data = parser.apply_translation(fp, changes)
                    if new_data is None:
                        reason = getattr(parser, "last_apply_error", None)
                        self.logger.warning(f"Failed to apply translations to {fp}: {reason or 'no data'}")
                        continue

                    # 3. Pre-write validation & serialization (same guards as the pipeline)
                    payload = self._serialize_for_write(fp, file_ext, parser, new_data)

                    # 4. Write atomically via safe_write
                    with safe_write(fp, "wb") as f:
                        f.write(payload)

                    # 5. Synchronize into TranslationCache with real original text, keyed the
                    #    same way ScanWorker looks entries up (settings source_lang).
                    if pipeline.cache:
                        orig_file_map = originals_by_file.get(fp, {})
                        for jp, trans_text in changes.items():
                            orig_text = orig_file_map.get(jp, trans_text)
                            pipeline.cache.set(orig_text, trans_text, source_lang, target_lang)

                    saved_files.append(fp)
                except Exception as file_exc:
                    self.logger.error(f"Error saving {fp}: {file_exc}")
                    backups = backup_mgr.get_backups_for_file(fp)
                    if backups:
                        backup_mgr.restore_backup(backups[-1], fp)
                        self.logger.info(f"Restored {fp} from backup following save error")

            if pipeline.cache:
                pipeline.cache.save()

            if saved_files:
                backup_mgr.create_session_manifest()
                self._store.mark_saved(saved_files)

                # Automatically isolate conflicting WOLF archives if WOLF project was saved
                try:
                    from src.core.parsers.wolf_isolation import isolate_conflicting_wolf_archives
                    isolated = isolate_conflicting_wolf_archives(project_dir)
                    if isolated:
                        self.logger.info("Isolated %d conflicting WOLF archive(s): %s", len(isolated), ", ".join(isolated))
                except Exception as iso_err:
                    self.logger.warning("Failed to isolate WOLF archives during save: %s", iso_err)

            self._refresh_page()
            self._refresh_stats()
            self.saveFinished.emit(True, f"{len(saved_files)} files saved and backed up successfully.")
        except Exception as exc:
            self.logger.error(f"Error during editor save: {exc}")
            self.saveFinished.emit(False, f"Save error: {exc}")

    @staticmethod
    def _serialize_for_write(fp: str, file_ext: str, parser: Any, new_data: Any) -> bytes:
        """Validate *new_data* against the on-disk original and return the bytes to write.

        Mirrors TranslationPipeline's pre-write guards: JSON structural roundtrip,
        tree-sitter JS syntax check, and Ruby Marshal roundtrip. Raises ValueError on
        any validation failure so the caller's backup-restore path handles it.
        """
        import orjson
        from src.core.validation import Validator
        from src.core.parsers.ts_adv_scenario_parser import TS_SCENARIO_EXTENSION

        if file_ext == ".json":
            try:
                with open(fp, "rb") as src:
                    original_json = orjson.loads(src.read())
            except Exception:
                original_json = None
            if original_json is not None:
                val_res = Validator.validate_json_roundtrip(original_json, new_data)
                if not val_res.is_valid:
                    raise ValueError(f"Pre-write JSON validation failed: {', '.join(val_res.errors)}")
                serialized = val_res.metadata.get("serialized_bytes")
                if serialized is not None:
                    return serialized
            return orjson.dumps(new_data)

        if file_ext == ".js":
            if isinstance(new_data, str):
                js_text = new_data
            else:
                prefix = getattr(parser, "_js_prefix", "var $plugins = \n")
                suffix = getattr(parser, "_js_suffix", ";\n")
                js_text = f"{prefix}{orjson.dumps(new_data).decode('utf-8')}{suffix}"
            val_res = Validator.validate_js_syntax(js_text)
            if not val_res.is_valid:
                raise ValueError(f"Pre-write JS validation failed: {', '.join(val_res.errors)}")
            return js_text.encode("utf-8")

        if file_ext in (".rvdata2", ".rxdata", ".rvdata"):
            val_res = Validator.validate_ruby_roundtrip(new_data)
            if not val_res.is_valid:
                raise ValueError(f"Pre-write Ruby validation failed: {', '.join(val_res.errors)}")
            if isinstance(new_data, bytes):
                return new_data
            import io
            import rubymarshal.writer
            buf = io.BytesIO()
            rubymarshal.writer.write(buf, new_data)
            return buf.getvalue()

        if file_ext in (".txt", ".csv", TS_SCENARIO_EXTENSION):
            return new_data.encode("utf-8") if isinstance(new_data, str) else bytes(new_data)

        if file_ext in (".mps", ".dat"):
            if not isinstance(new_data, (bytes, bytearray)):
                raise ValueError(f"Pre-write WOLF validation failed: Expected bytes payload, got {type(new_data)}")
            raw_bytes = bytes(new_data)
            val_res = Validator.validate_wolf_roundtrip(raw_bytes, file_ext, fp)
            if not val_res.is_valid:
                raise ValueError(f"Pre-write WOLF validation failed: {', '.join(val_res.errors)}")
            return raw_bytes

        raise ValueError(f"Unsupported extension for editor save: {file_ext}")

    def _on_project_path_changed(self, new_path: str = "") -> None:
        """Clear stale editor state when another tab changes the active folder."""
        if self._scan_worker and self._scan_worker.isRunning():
            try:
                self._scan_worker.progress.disconnect()
                self._scan_worker.finished.disconnect()
            except Exception:
                pass
            self._scan_worker.wait(1000)
            self._is_scanning = False
            self.isScanningChanged.emit()

        if self._store:
            self._store.close()
            self._store = None
        self._project_loaded = False
        self._scan_attempted = False
        self._selected_entry = {}
        self._selected_entry_id = 0
        self._table_model.set_rows([])
        self._total_count = 0
        self._total_project_count = 0
        self.projectLoadedChanged.emit()
        self.selectedEntryChanged.emit()
        self._refresh_stats()

    def _on_pipeline_finished(self, success: bool, _summary: str) -> None:
        """When automatic translation pipeline finishes, refresh editor database."""
        if success and self._project_loaded:
            self.loadProject(force_rescan=True)
