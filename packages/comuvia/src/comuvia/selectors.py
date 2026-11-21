"""Check and build source-assertion quote, position and media-time selectors.

The caller supplies retained bytes and optional timeline metadata; nothing is fetched and
no locator is dereferenced. Positions are Unicode code points over UTF-8-decoded text,
end-exclusive.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from . import reasons
from .builders import _MARKER_CODE, _has_surrogate, _plain_copy, not_applicable_marker
from .identity import content_digest, is_marker
from .issues import Issue, RefusalError
from .validation import as_integer


@dataclass(frozen=True)
class SelectorCheck:
    result: str  # "match" | "mismatch" | "unavailable"
    checked: tuple[str, ...]
    issues: tuple[Issue, ...]


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _norm_ws(text: str) -> str:
    return " ".join(text.split())


def _validate_media_time(media_time) -> dict:
    if not isinstance(media_time, Mapping):
        raise RefusalError([Issue("/selector/media_time", reasons.INVALID_SELECTOR, "media_time must be a mapping or None")])
    keys = set(media_time)
    for marker_key in ("unknown", "withheld"):
        if marker_key in keys and keys <= {marker_key, "note"}:
            code = media_time.get(marker_key)
            if not isinstance(code, str) or _MARKER_CODE.match(code) is None:
                raise RefusalError([Issue(f"/selector/media_time/{marker_key}", reasons.INVALID_MARKER, "invalid marker code")])
            if "note" in keys:
                note = media_time["note"]
                if not isinstance(note, str) or note == "":
                    raise RefusalError([Issue("/selector/media_time/note", reasons.INVALID_MARKER, "marker note must be a non-empty string")])
                if _has_surrogate(note):
                    raise RefusalError([Issue("/selector/media_time/note", reasons.LONE_SURROGATE, "marker note contains an unpaired surrogate")])
            return _plain_copy(media_time)
    if keys != {"start_seconds", "end_seconds"}:
        raise RefusalError([
            Issue("/selector/media_time", reasons.INVALID_SELECTOR,
                  "media_time must be a valid marker or {'start_seconds', 'end_seconds'}")
        ])
    s0, s1 = media_time["start_seconds"], media_time["end_seconds"]
    if not (_is_finite_number(s0) and _is_finite_number(s1) and 0 <= s0 <= s1):
        raise RefusalError([
            Issue("/selector/media_time", reasons.INVALID_SELECTOR,
                  "media_time requires finite numbers with 0 <= start_seconds <= end_seconds")
        ])
    return _plain_copy(media_time)


def locate_quote(
    exact: str,
    content: bytes | bytearray | memoryview | str,
    *,
    context_chars: int = 32,
    max_context_chars: int = 256,
    occurrence: int | None = None,
    media_time: Mapping | None = None,
) -> dict:
    """Locate ``exact`` in ``content`` and return a schema-valid ``selector`` object.

    Refuses ``quote_mismatch`` when ``exact`` is absent and ``ambiguous_quote`` when
    ``exact`` occurs multiple times (unless ``occurrence`` explicitly selects one and
    widened prefix/suffix context up to ``max_context_chars`` disambiguates it uniquely).
    """
    if not isinstance(exact, str) or exact == "":
        raise RefusalError([Issue("/quote/exact", reasons.INVALID_SELECTOR, "exact quote must be a non-empty string")])
    if _has_surrogate(exact):
        raise RefusalError([Issue("/quote/exact", reasons.LONE_SURROGATE, "exact quote contains an unpaired surrogate")])
    if isinstance(context_chars, bool) or not isinstance(context_chars, int) or context_chars < 0:
        raise RefusalError([Issue("/context_chars", reasons.INVALID_SELECTOR, "context_chars must be a non-negative integer")])
    if isinstance(max_context_chars, bool) or not isinstance(max_context_chars, int) or max_context_chars < context_chars:
        raise RefusalError([Issue("/max_context_chars", reasons.INVALID_SELECTOR, "max_context_chars must be >= context_chars")])

    if isinstance(content, (bytes, bytearray, memoryview)):
        try:
            text = bytes(content).decode("utf-8")
        except UnicodeDecodeError as error:
            raise RefusalError([Issue("/content", reasons.INVALID_UTF8, str(error))]) from None
    elif isinstance(content, str):
        if _has_surrogate(content):
            raise RefusalError([Issue("/content", reasons.LONE_SURROGATE, "content string contains an unpaired surrogate")])
        text = content
    else:
        raise RefusalError([Issue("/content", reasons.INVALID_CONTENT_INPUT, "content must be UTF-8 bytes or str")])

    mt = _validate_media_time(media_time) if media_time is not None else not_applicable_marker(
        note="text resource: it has no timeline"
    )

    starts: list[int] = []
    pos = text.find(exact, 0)
    while pos != -1:
        starts.append(pos)
        pos = text.find(exact, pos + 1)

    if not starts:
        raise RefusalError([Issue("/quote/exact", reasons.QUOTE_MISMATCH, "verbatim quote does not occur in the bytes")])

    if occurrence is None:
        if len(starts) > 1:
            raise RefusalError([
                Issue("/quote/exact", reasons.AMBIGUOUS_QUOTE,
                      f"quote occurs {len(starts)} times; pass occurrence= to select one")
            ])
        start = starts[0]
    else:
        if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 0 or occurrence >= len(starts):
            raise RefusalError([
                Issue("/occurrence", reasons.OUT_OF_RANGE,
                      f"occurrence {occurrence!r} is out of range for {len(starts)} match(es)")
            ])
        start = starts[occurrence]

    end = start + len(exact)
    widths = [context_chars]
    probe = max(context_chars * 2, context_chars + 16)
    while probe < max_context_chars:
        widths.append(probe)
        probe *= 2
    if max_context_chars not in widths:
        widths.append(max_context_chars)

    chosen_prefix: str | None = None
    chosen_suffix: str | None = None
    for width in widths:
        prefix = text[max(0, start - width):start]
        suffix = text[end:min(len(text), end + width)]
        anchored = prefix + exact + suffix
        first = text.find(anchored)
        if first != -1 and text.find(anchored, first + 1) == -1 and text.count(anchored) == 1:
            chosen_prefix, chosen_suffix = prefix, suffix
            break

    if chosen_prefix is None or chosen_suffix is None:
        raise RefusalError([
            Issue("/selector/text_quote", reasons.AMBIGUOUS_QUOTE,
                  "prefix + exact + suffix does not uniquely identify the occurrence within max_context_chars")
        ])

    return {
        "text_quote": {
            "exact": exact,
            "prefix": chosen_prefix,
            "suffix": chosen_suffix,
        },
        "text_position": {
            "start": start,
            "end": end,
        },
        "media_time": mt,
    }


def check_selector(
    assertion: Mapping,
    content: bytes | None,
    *,
    snapshot: Mapping | None = None,
    media_duration: float | int | None = None,
    timed_segments: Iterable[Mapping] | None = None,
    time_tolerance: float = 0.5,
) -> SelectorCheck:
    """Check ``assertion`` against ``content`` and optional timeline bounds/segments.

    If ``snapshot`` is given, ``content`` must match its content digest first.
    ``verbatim: true`` requires the quote to occur in the text (else ``quote_mismatch``);
    every selector given as a value must select the quote (else ``selector_mismatch``).
    When ``media_duration`` or ``timed_segments`` is given and ``selector.media_time`` is
    a ``{start, end}`` span (not a marker), ``media_time`` is also checked.
    """
    segments_list = list(timed_segments) if timed_segments is not None else None
    if content is None and media_duration is None and segments_list is None:
        return SelectorCheck("unavailable", (), ())

    checked: list[str] = []
    issues: list[Issue] = []
    quote = assertion["quote"]
    exact = quote["exact"]

    if content is not None:
        if snapshot is not None:
            expected = snapshot.get("content", {}).get("digest")
            if not isinstance(expected, str) or expected != content_digest(content):
                return SelectorCheck("mismatch", ("content",), (
                    Issue("/resource", reasons.CONTENT_DIGEST_MISMATCH, "bytes are not the snapshot's retained content"),
                ))
        try:
            text = bytes(content).decode("utf-8")
        except UnicodeDecodeError:
            return SelectorCheck("unavailable", (), ())

        if quote.get("verbatim") is True:
            checked.append("quote")
            if exact not in text:
                issues.append(Issue("/quote/exact", reasons.QUOTE_MISMATCH, "verbatim quote does not occur in the bytes"))

        selector = assertion.get("selector", {})
        text_quote = selector.get("text_quote")
        if isinstance(text_quote, Mapping) and not is_marker(text_quote):
            checked.append("text_quote")
            anchored = text_quote.get("prefix", "") + text_quote["exact"] + text_quote.get("suffix", "")
            if text.count(anchored) != 1:
                issues.append(Issue("/selector/text_quote", reasons.SELECTOR_MISMATCH,
                                    "prefix + exact + suffix does not occur exactly once"))
        position = selector.get("text_position")
        if isinstance(position, Mapping) and not is_marker(position):
            checked.append("text_position")
            start, end = as_integer(position.get("start")), as_integer(position.get("end"))
            if start is None or end is None or end > len(text) or text[start:end] != exact:
                issues.append(Issue("/selector/text_position", reasons.SELECTOR_MISMATCH,
                                    "code-point range does not select the quote"))

    selector = assertion.get("selector", {})
    media_time = selector.get("media_time")
    if (media_duration is not None or segments_list is not None) and isinstance(media_time, Mapping) and not is_marker(media_time):
        checked.append("media_time")
        mt_start, mt_end = media_time.get("start_seconds"), media_time.get("end_seconds")
        if not (_is_finite_number(mt_start) and _is_finite_number(mt_end) and 0 <= mt_start <= mt_end):
            issues.append(Issue("/selector/media_time", reasons.SELECTOR_MISMATCH, "media_time start_seconds/end_seconds range is invalid"))
        else:
            if media_duration is not None:
                if not _is_finite_number(media_duration) or media_duration < 0 or mt_end > media_duration + 1e-9:
                    issues.append(Issue("/selector/media_time", reasons.SELECTOR_MISMATCH,
                                        "media_time exceeds media_duration"))
            if segments_list is not None and quote.get("verbatim") is True:
                tol = float(time_tolerance) if _is_finite_number(time_tolerance) and time_tolerance >= 0 else 0.0
                overlapping: list[str] = []
                for seg in segments_list:
                    if not isinstance(seg, Mapping):
                        continue
                    s0 = seg.get("start_seconds", seg.get("start"))
                    s1 = seg.get("end_seconds", seg.get("end"))
                    seg_text = seg.get("text")
                    if _is_finite_number(s0) and _is_finite_number(s1) and 0 <= s0 <= s1 and isinstance(seg_text, str):
                        if s1 >= mt_start - tol and s0 <= mt_end + tol:
                            overlapping.append(seg_text)
                norm_exact = _norm_ws(exact)
                if norm_exact:
                    matched_window = bool(overlapping) and norm_exact in _norm_ws(" ".join(overlapping))
                else:
                    matched_window = any(exact in seg_text for seg_text in overlapping)
                if not matched_window:
                    issues.append(Issue("/selector/media_time", reasons.SELECTOR_MISMATCH,
                                        "verbatim quote does not occur within the selected media_time window"))

    if not checked:
        return SelectorCheck("unavailable", (), ())
    return SelectorCheck("mismatch" if issues else "match", tuple(checked), tuple(issues))
