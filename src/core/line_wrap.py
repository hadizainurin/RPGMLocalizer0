"""Word-wrap translated message text so it fits the game's message window.

Japanese packs a line into far fewer characters than English: a line of 24
Japanese characters becomes ~70 English ones. The model also tends to merge
the original's lines. Written as-is, the text runs off the right edge of the
window. This module re-breaks long lines at spaces before the text is saved.

Rules (all deliberate):
- Lines are only ever SPLIT, never joined. A speaker name on its own first
  line ("Announcer") stays there, and wrapping already-wrapped text changes
  nothing, so it is safe to run on every load and every Save.
- Game codes (\\c[2], \\f[24], \\A+, <<...>>) take no width and are never cut.
  \\i[n] counts as one icon; substitutions such as \\v[n] / \\s[n] count as a
  short word, because their value is only known at runtime.
- A continuation line keeps the indentation of the line it came from.
- Width is measured in half-width units: an ASCII character is 1, a
  full-width (Japanese) character is 2.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

from src.core.text_segmenter import SegmentType, segment_text

#: Engines whose files get wrapped. Only WOLF for now: RPG Maker has its own
#: wrap in the pipeline (<WordWrap> / plugins) and its codes mean other things
#: (in RPG Maker \f is not a font size).
WRAP_FILE_EXTENSIONS = (".dat", ".mps")

#: Editor tags that are message-window text. Choices, battle messages and
#: picture text are single-line slots and must not gain line breaks.
WRAP_TAGS = ("string_op", "dialogue", "message")

#: Lines a WOLF message window shows. 4-line messages are common in the
#: original games; anything taller can run past the bottom of the window.
DEFAULT_MAX_LINES = 4

#: An English letter is slightly wider than half a Japanese character in the
#: proportional fonts these games use (measured: ~12.3 px vs 22 px per
#: full-width character), so the automatic width is trimmed by this factor.
LATIN_WIDTH_FACTOR = 0.89

#: Never wrap narrower than this (in English characters): a short original
#: says nothing about the window's real width.
MIN_AUTO_WIDTH = 30

_FONT_SIZE_RE = re.compile(r"\\f\[(\d+)\]")
_RUBY_RE = re.compile(r"\\r\[([^,\]]*),[^\]]*\]", re.IGNORECASE)
_ICON_RE = re.compile(r"\\i\[\d+\]", re.IGNORECASE)
_SUBST_RE = re.compile(r"\\(?:v|s|self|cself|cdb|udb|sdb|cu|n)\d*\[", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
_INDENT_RE = re.compile(r"^[ \t\u3000]*")


def _char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _code_width(code: str) -> int:
    m = _RUBY_RE.fullmatch(code)
    if m:
        return text_width(m.group(1))
    if _ICON_RE.fullmatch(code):
        return 2
    if _SUBST_RE.match(code):
        return 4
    return 0


def text_width(text: str) -> int:
    """Visible width of one line in half-width units (codes excluded)."""
    total = 0
    for seg in segment_text(text):
        if seg.type == SegmentType.CODE:
            total += _code_width(seg.content)
        else:
            total += sum(_char_width(ch) for ch in seg.content)
    return total


def font_size(text: str) -> Optional[int]:
    """Font size the message starts in: a \\f[n] code before any visible text (WOLF).

    A size change later in the message (a small footnote line) does not
    count: the first lines are still in the normal size and must fit.
    """
    size: Optional[int] = None
    for seg in segment_text(text or ""):
        if seg.type == SegmentType.TEXT:
            if seg.content.strip():
                break
            continue
        # Adjacent codes arrive as one segment ("\\c[02]\\f[24]\\A+").
        for m in _FONT_SIZE_RE.finditer(seg.content):
            size = int(m.group(1))
    return size


def _atoms(line: str) -> list[tuple[str, int, bool]]:
    """Split a line into (piece, width, is_code) atoms; text is one atom per char."""
    atoms: list[tuple[str, int, bool]] = []
    for seg in segment_text(line):
        if seg.type == SegmentType.CODE:
            atoms.append((seg.content, _code_width(seg.content), True))
        else:
            atoms.extend((ch, _char_width(ch), False) for ch in seg.content)
    return atoms


def _wrap_line(line: str, limit: int) -> list[str]:
    if text_width(line) <= limit:
        return [line]
    indent = _INDENT_RE.match(line).group(0)
    indent_w = text_width(indent)
    atoms = _atoms(line)
    out: list[str] = []
    cur: list[tuple[str, int, bool]] = []
    width = 0
    seen_text = False   # the indentation is not a break point
    for atom in atoms:
        piece, w, is_code = atom
        cur.append(atom)
        width += w
        if not is_code and piece.strip():
            seen_text = True
        if width <= limit:
            continue
        # Over the limit: break at the last space, or before the last
        # Japanese character (no spaces between those).
        cut = None
        for i in range(len(cur) - 1, 0, -1):
            p, _, c = cur[i]
            if c:
                continue
            if p in (" ", "\u3000") and any(not a[2] and a[0].strip() for a in cur[:i]):
                cut = (i, i + 1)        # drop the space itself
                break
            if _CJK_RE.match(p) and i < len(cur) and any(not a[2] and a[0].strip() for a in cur[:i]):
                cut = (i, i)
                break
        if cut is None or not seen_text:
            continue                    # one long word: leave it rather than cut it
        head = "".join(a[0] for a in cur[:cut[0]]).rstrip(" \u3000")
        out.append(head)
        rest = cur[cut[1]:]
        cur = [(indent, indent_w, True)] + rest if indent else rest
        width = sum(a[1] for a in cur)
    if cur:
        out.append("".join(a[0] for a in cur))
    return out


def wrap_text(text: str, limit: int) -> str:
    """Re-break every line of *text* that is wider than *limit* units."""
    if not text or limit <= 0:
        return text
    lines = text.split("\n")
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_line(line, limit))
    return "\n".join(wrapped)


@dataclass
class WrapWidth:
    """Window width learned from the game's own Japanese text."""
    units: int              # width in half-width units at ref_size
    ref_size: Optional[int]  # most common \\f[n] size, or None

    def limit_for(self, original: str) -> int:
        size = font_size(original)
        units = self.units
        if size and self.ref_size and size != self.ref_size:
            units = int(units * self.ref_size / size)
        return max(MIN_AUTO_WIDTH, int(units * LATIN_WIDTH_FACTOR))


def learn_width(originals: Iterable[str], percentile: float = 0.999) -> Optional[WrapWidth]:
    """Estimate the window width from the original message lines.

    The widest lines the game's author wrote (99.9th percentile, so a
    stray overlong line does not count) show how much fits in the window.
    Lines in a different font size are scaled to the most common size.
    """
    from collections import Counter
    texts = [t for t in originals if t and _CJK_RE.search(t)]
    if not texts:
        return None
    sizes = Counter(s for s in (font_size(t) for t in texts) if s)
    ref = sizes.most_common(1)[0][0] if sizes else None
    widths: list[float] = []
    for t in texts:
        size = font_size(t)
        scale = (size / ref) if (size and ref) else 1.0
        for line in t.split("\n"):
            if _CJK_RE.search(line):
                widths.append(text_width(line) * scale)
    if not widths:
        return None
    widths.sort()
    return WrapWidth(units=int(widths[int(percentile * (len(widths) - 1))]), ref_size=ref)


def should_wrap(file_path: str, tag: str) -> bool:
    return (file_path or "").lower().endswith(WRAP_FILE_EXTENSIONS) and (tag or "") in WRAP_TAGS
