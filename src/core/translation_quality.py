"""Structural checks for translated RPG text."""
from __future__ import annotations

from collections import Counter
import re

from src.core.text_segmenter import SegmentType, segment_text


_PLACEHOLDER_RE = re.compile(r"\$\{[^{}]+\}|\{[A-Za-z_][A-Za-z_0-9]*\}|%(?:\d+\$)?[sdif]")

#: How many line breaks a translation may gain or lose before it is sent back
#: for a second attempt. Natural reflow of one line is normal and harmless.
LINE_BREAK_TOLERANCE = 1


#: Issues that make a line unsafe to write into game data. A changed line-break
#: count is only a layout problem, so it is not on this list.
GAME_BREAKING_ISSUES = ("empty translation", "game codes or tags changed", "format placeholders changed")


def breaks_game(original: str, translated: str) -> bool:
    """True if writing `translated` over `original` could break the game.

    The gate for every path that reuses a stored translation without a person
    looking at it: Patch from Cache, the scan-time cache lookup, and the
    cache Save writes to.
    """
    return any(issue in GAME_BREAKING_ISSUES for issue in translation_issues(original, translated))


_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
_LETTER_RE = re.compile(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
_BRACKET_CODE_RE = re.compile(r"\\[A-Za-z]+\d*\[[^\]]*\]")
_CJK_TARGETS = ("ja", "zh", "ko")


def still_untranslated(translated: str, target_lang: str) -> bool:
    """True if a 'translation' into a non-CJK language is still mostly Japanese.

    Saves made while WOLF files were wrongly downgraded to CP932 read back as
    the original with its dakuten and symbols stripped (です -> てす, ♥ -> ?).
    That text differs from the original, so it was stored as a translation.
    Ruby codes like \\r[我,わ] are ignored when counting.
    """
    if not translated or (target_lang or "").lower().startswith(_CJK_TARGETS):
        return False
    text = _BRACKET_CODE_RE.sub("", translated)
    letters = len(_LETTER_RE.findall(text))
    return bool(letters) and len(_CJK_RE.findall(text)) / letters > 0.3


def safe_to_reuse(original: str, translated: str, target_lang: str) -> bool:
    """Gate for a stored translation that will be written without review."""
    return not breaks_game(original, translated) and not still_untranslated(translated, target_lang)


def translation_issues(original: str, translated: str) -> list[str]:
    """Return reasons a translation needs review before writing game data."""
    if not translated or not translated.strip():
        return ["empty translation"]
    issues: list[str] = []
    source_codes = Counter(segment.content for segment in segment_text(original) if segment.type == SegmentType.CODE)
    translated_codes = Counter(segment.content for segment in segment_text(translated) if segment.type == SegmentType.CODE)
    if source_codes != translated_codes:
        issues.append("game codes or tags changed")
    if Counter(_PLACEHOLDER_RE.findall(original)) != Counter(_PLACEHOLDER_RE.findall(translated)):
        issues.append("format placeholders changed")
    # A changed line-break count is a layout nuisance, not a corruption risk:
    # escape codes and placeholders are checked above and are what actually
    # break a game. Treating every reflowed line as a failure sent a second
    # translation request for a large share of a run, which dominated cost on
    # big projects. Only flag it when the difference is large enough that the
    # engine would genuinely mis-render the box.
    source_breaks = original.count("\n")
    target_breaks = translated.count("\n")
    if source_breaks and abs(source_breaks - target_breaks) > LINE_BREAK_TOLERANCE:
        issues.append("line break count changed")
    elif not source_breaks and target_breaks > LINE_BREAK_TOLERANCE:
        issues.append("line break count changed")
    return issues
