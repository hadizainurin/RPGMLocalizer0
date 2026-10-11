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


def wrap_text(text: str, limit: int, max_lines: int = 0, keep_first: bool = False) -> str:
    """Re-break every line of *text* that is wider than *limit* units.

    With *max_lines*, a message that would come out taller than that is
    re-flowed instead: its lines are joined into one paragraph and wrapped
    again, so the model's own short breaks ("...no matter what\nit takes.")
    stop costing a line each. Seen in False Myth 2: a 4-line original became
    7 lines and the last one fell below the window. *keep_first* keeps line 1
    on its own (the speaker's name, "Velka").
    """
    if not text or limit <= 0:
        return text
    lines = text.split("\n")
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(_wrap_line(line, limit))
    if not max_lines or len(wrapped) <= max_lines:
        return "\n".join(wrapped)
    head = lines[:1] if keep_first and len(lines) > 1 else []
    body = lines[len(head):]
    joined = " ".join(part.strip(" \t\u3000") for part in body if part.strip(" \t\u3000"))
    reflowed = head + _wrap_line(joined, limit)
    return "\n".join(reflowed if len(reflowed) < len(wrapped) else wrapped)


def has_speaker_line(original: str) -> bool:
    """True if the original's first line is a speaker name above the speech.

    WOLF games write it as a short line followed by a line opening with 「, 『
    or （, e.g. "ヴェルカ\n「…でも後悔はしないわ。".
    """
    lines = (original or "").split("\n")
    if len(lines) < 2:
        return False
    first = lines[0]
    visible = "".join(seg.content for seg in segment_text(first) if seg.type == SegmentType.TEXT).strip()
    second = "".join(seg.content for seg in segment_text(lines[1]) if seg.type == SegmentType.TEXT).lstrip(" \u3000")
    return (0 < len(visible) <= 12 and not any(ch in visible for ch in "「」『』。！？")
            and second[:1] in ("「", "『", "（", "("))


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


# ---------------------------------------------------------------------------
# Smaller font for messages that are still too tall after wrapping
# ---------------------------------------------------------------------------
#: Never shrink below this share of the message's normal size: much smaller
#: and the text becomes hard to read.
DEFAULT_MIN_FONT_SIZE = 18


def restore_font_codes(original: str, text: str) -> str:
    """Undo an earlier shrink, so the font is always fitted from scratch.

    The \\f[n] codes of the translation are reset to the original's values
    (the code check guarantees the same count), and a size code the original
    did not start with - one this module added - is removed.
    """
    orig_sizes = _FONT_SIZE_RE.findall(original or "")
    if font_size(original) is None and font_size(text) is not None:
        # Drop the leading code we inserted (the model never adds one: the
        # code check would have rejected it).
        m = _FONT_SIZE_RE.search(text)
        text = text[:m.start()] + text[m.end():]
    found = list(_FONT_SIZE_RE.finditer(text))
    if len(found) != len(orig_sizes):
        return text
    out, pos = [], 0
    for m, size in zip(found, orig_sizes):
        out.append(text[pos:m.start()])
        out.append("\\f[%s]" % size)
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def scale_font(text: str, base: int, size: int) -> str:
    """Make the whole message *size*/*base* times as big.

    Every \\f[n] in it is scaled (a smaller footnote stays smaller); if the
    message does not start with one, \\f[size] is put in front.
    """
    if size == base:
        return text
    scaled = _FONT_SIZE_RE.sub(lambda m: "\\f[%d]" % max(1, round(int(m.group(1)) * size / base)), text)
    if font_size(text) is None:
        scaled = "\\f[%d]%s" % (size, scaled)
    return scaled


def fit_message(text: str, limit: int, max_lines: int, keep_first: bool,
                base_size: int, min_size: int) -> tuple[str, int, int]:
    """Wrap *text*; if it is still too tall, try smaller font sizes.

    *limit* and *max_lines* are for *base_size*. At size s a line holds
    base/s times as many characters and the window base/s times as many
    lines. The largest size that fits wins. Returns (text, lines, size used);
    when nothing fits, the text is wrapped at the normal size.
    """
    wrapped = wrap_text(text, limit, max_lines, keep_first)
    lines = wrapped.count("\n") + 1
    if lines <= max_lines or not base_size or min_size >= base_size:
        return wrapped, lines, base_size
    for size in range(base_size - 1, min_size - 1, -1):
        lim = int(limit * base_size / size)
        cap = int(max_lines * base_size / size + 1e-9)
        cand = wrap_text(text, lim, cap, keep_first)
        n = cand.count("\n") + 1
        if n <= cap:
            return scale_font(cand, base_size, size), n, size
    return wrapped, lines, base_size
