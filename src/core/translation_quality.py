"""Structural checks for translated RPG text."""
from __future__ import annotations

from collections import Counter
import re

from src.core.text_segmenter import SegmentType, segment_text


_PLACEHOLDER_RE = re.compile(r"\$\{[^{}]+\}|\{[A-Za-z_][A-Za-z_0-9]*\}|%(?:\d+\$)?[sdif]")

#: How many line breaks a translation may gain or lose before it is sent back
#: for a second attempt. Natural reflow of one line is normal and harmless.
LINE_BREAK_TOLERANCE = 1


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
