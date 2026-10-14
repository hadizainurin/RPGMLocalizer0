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
GAME_BREAKING_ISSUES = ("empty translation", "game codes or tags changed", "format placeholders changed",
                        "internal separator left in text", "reply debris in text")

#: Pieces of the model's reply format that ended up inside a line: '"]}```',
#: "(Note: ...", a JSON key, a stray brace - and the model reading its own
#: instructions back ("(Engine codes unchanged: ...) (No filename translation:
#: ...) (All constraints met.)", False Myth 2 event 777), which comes without
#: any JSON around it. The phrases are the headings of the prompt's rules.
_DEBRIS_RE = re.compile(
    r"```|\]\s*\}|\(Note:|\"t\"\s*:"
    r"|\((?:Engine codes|No filename|All constraints|Adult tone|JSON format|Preserved register)"
)

#: The app's own segment markers. One in a translation means reassembly
#: failed; the text around it is unreliable (codes moved, parts untranslated).
_FONT_CODE_RE = re.compile(r"\\f\[\d+\]")
_INTERNAL_MARKER_RE = re.compile(r"TXT\s*SEG|RPGMSEP|SEP777|ТХЦЭГ|THCEG", re.IGNORECASE)


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


_ROMAJI_WORD_RE = re.compile(
    r"^(?:(?:ky|gy|sh|ch|ts|ny|hy|by|py|my|ry|j|f|[kgsztdnhbpmyrw])?[aeiouāēīōū]|n(?![aeiouy])|"
    r"(?<=[aeiou])[kgsztdpbcm](?=[kgsztdpbcm]))+$"
)
_ROMAJI_PARTICLES = frozenset(
    "no ni wo wa ga de to mo ka ne yo da desu dayo dakedo kara kedo shi zo sa na naa nai".split()
)


def looks_romanized(original: str, translated: str) -> bool:
    """True if a 'translation' of Japanese is the Japanese written in romaji.

    Seen in payload logs: "…H-honki ka? Zettai…kurou suru koto ni naru to omou
    zo…" for 「…ほ、本気か？ 絶対…苦労することになると思うぞ…」. It is Latin
    text, so the still-Japanese check passed it. English sentences rarely have
    most words spelled as romaji syllables *and* several Japanese particles.
    """
    if not translated or not _CJK_RE.search(original or ""):
        return False
    text = _BRACKET_CODE_RE.sub(" ", translated).lower()
    words = re.findall(r"[a-zāēīōū]+", text)
    if len(words) < 5:
        return False
    romaji = sum(1 for w in words if _ROMAJI_WORD_RE.match(w))
    particles = sum(1 for w in words if w in _ROMAJI_PARTICLES)
    return romaji / len(words) >= 0.8 and particles >= 2


def safe_to_reuse(original: str, translated: str, target_lang: str) -> bool:
    """Gate for a stored translation that will be written without review."""
    return (not breaks_game(original, translated)
            and not still_untranslated(translated, target_lang)
            and not looks_romanized(original, translated)
            and not looks_cut_off(original, translated))


def _visible(text: str) -> str:
    return "".join(seg.content for seg in segment_text(text or "") if seg.type == SegmentType.TEXT)


_WORD_CHAR_RE = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def looks_cut_off(original: str, translated: str) -> bool:
    """True if a machine translation is far too short to be the whole line.

    English runs ~2x the characters of the Japanese it translates (1% of
    real lines fall below 0.95x). Seen in the game: "t", " is ", " and " for
    three-line messages - a broken reply split into the wrong pieces. Only
    applied to machine output: a person may shorten a line on purpose.
    """
    src = _visible(original).strip()
    src_words = len(_WORD_CHAR_RE.findall(src))
    if src_words < 8 or not _CJK_RE.search(src) or convert_sound_only(original) is not None:
        return False        # short lines ("「えっ…！！？」" -> "Eh…!!?") can be short in English too
    words = _WORD_CHAR_RE.findall(_visible(translated))
    return len(words) < max(3, int(0.3 * src_words))


def is_damaged_translation(original: str, translated: str, source_lang: str, target_lang: str) -> bool:
    """True if a stored machine translation must not stay in the project.

    Used on every project load (full scan and quick load) so a bad line is
    discarded the moment it is seen, not carried forward.
    """
    if not translated or translated == original:
        return False
    from src.core.text_segmenter import has_translatable_content
    return (
        not has_translatable_content(original, source_lang)
        or breaks_game(original, translated)
        or still_untranslated(translated, target_lang)
        or looks_romanized(original, translated)
        or looks_cut_off(original, translated)
    )


def _codes_changed(original: str, translated: str) -> bool:
    """True if a game code of the original is missing, or a new one appeared.

    Re-tokenising the translation was not reliable: a WOLF bare code followed
    by an English letter reads differently from the same code followed by
    Japanese ("\\E同行条件" vs "\\EParty Condition" - \\E is only a code
    when no letter follows). Every reassembled line starting with \\E + a
    letter was "damaged", reset to Japanese on the next load, translated
    again, and reset again (120 rows per load in False Myth 2). So each code
    run of the original is looked up in the translation as written.
    """
    # Font size (WOLF \\f[n]) is layout, not logic: the word-wrap pass shrinks
    # it for messages that are too tall. Compare without it.
    original = _FONT_CODE_RE.sub("", original)
    translated = _FONT_CODE_RE.sub("", translated)
    runs = [seg.content for seg in segment_text(original) if seg.type == SegmentType.CODE]
    rest = translated
    for run in sorted(runs, key=len, reverse=True):
        at = rest.find(run)
        if at < 0:
            return True
        rest = rest[:at] + "\x00" + rest[at + len(run):]
    for seg in segment_text(rest):
        if seg.type != SegmentType.CODE:
            continue
        if "\x00" in seg.content:
            continue        # a bracket pair around a known code: "[\\cself[12]]" from 【】
        leftover = seg.content
        if any(leftover in run for run in runs):
            continue
        return True
    return False


def translation_issues(original: str, translated: str) -> list[str]:
    """Return reasons a translation needs review before writing game data."""
    if not translated or not translated.strip():
        return ["empty translation"]
    issues: list[str] = []
    if _INTERNAL_MARKER_RE.search(translated) and not _INTERNAL_MARKER_RE.search(original):
        issues.append("internal separator left in text")
    if ((_DEBRIS_RE.search(translated) and not _DEBRIS_RE.search(original))
            or (("{" in translated or "}" in translated) and "{" not in original and "}" not in original)):
        issues.append("reply debris in text")
    # Every word gone, codes left: "\\c[02]\\f[24]\\A+\\n" for a three-line message.
    if (_CJK_RE.search(_visible(original)) and convert_sound_only(original) is None
            and not _WORD_CHAR_RE.search(_visible(translated))):
        return ["empty translation"] + issues
    if looks_romanized(original, translated):
        issues.append("written in romaji, not translated")
    if _codes_changed(original, translated):
        issues.append("game codes or tags changed")
    elif original.count("<") != translated.count("<") or original.count(">") != translated.count(">"):
        # Angle brackets are script syntax in these engines (<<GET_SOUNDTIME>>);
        # a model that drops or adds one breaks the line even when every
        # recognised code survived.
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


# ---------------------------------------------------------------------------
# Lines that are only a sound: 「っ！！！？」, ……っ！！！, ーーー
# ---------------------------------------------------------------------------
#: Small kana and the long-vowel mark carry no word on their own: っ is the
#: catch of breath before a shout. A local model returns such a line unchanged,
#: so it failed the "still Japanese" check on every run and stayed Untranslated.
_SOUND_ONLY_DROP = set("っッぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")
_SOUND_ONLY_MAP = {
    "ー": "—", "〜": "~", "～": "~", "！": "!", "？": "?", "、": ",", "。": ".",
    "「": '"', "」": '"', "『": '"', "』": '"', "（": "(", "）": ")", "‥": "…",
    "　": "　",
}
_SOUND_ONLY_KEEP = set("…・♪♫♥♡☆★!?~.,()\"' \t\r\n—-")


def convert_sound_only(text: str, target_lang: str = "en") -> str | None:
    """English rendering of a line that is only a sound and punctuation, else None.

    「っ！！！？」 becomes "!!!?", ……っ！！！ becomes ……!!!, ーーー becomes ———.
    Game codes are kept as they are. Lines with any real word return None and
    go to the translator as usual.
    """
    if not text or (target_lang or "").lower().startswith(_CJK_TARGETS):
        return None
    out: list[str] = []
    saw_japanese = False
    for seg in segment_text(text):
        if seg.type == SegmentType.CODE:
            out.append(seg.content)
            continue
        for ch in seg.content:
            if ch in _SOUND_ONLY_DROP:
                saw_japanese = True
            elif ch in _SOUND_ONLY_MAP:
                saw_japanese = saw_japanese or ch in "ー〜"
                out.append(_SOUND_ONLY_MAP[ch])
            elif ch in _SOUND_ONLY_KEEP:
                out.append(ch)
            else:
                return None     # a real character: let the model translate it
    if not saw_japanese:
        return None
    result = "".join(out)
    visible = [seg.content for seg in segment_text(result) if seg.type == SegmentType.TEXT]
    if not "".join(visible).strip(" 　\"'\r\n\t"):
        result = result.replace('""', '"…"') if '""' in result else result + "…"
    return result
