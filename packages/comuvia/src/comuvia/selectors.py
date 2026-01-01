"""Check a source assertion's quote and selectors against retained resource bytes.

The caller supplies the bytes; nothing is fetched and no locator is dereferenced.
Positions are Unicode code points over the UTF-8-decoded text, end-exclusive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from . import reasons
from .identity import content_digest, is_marker
from .issues import Issue
from .validation import as_integer


@dataclass(frozen=True)
class SelectorCheck:
    result: str  # "match" | "mismatch" | "unavailable"
    checked: tuple[str, ...]
    issues: tuple[Issue, ...]


def check_selector(assertion: Mapping, content: bytes | None, *, snapshot: Mapping | None = None) -> SelectorCheck:
    """Check ``assertion`` against ``content``, the retained bytes of its resource.

    If ``snapshot`` is given, the bytes must match its content digest first.
    ``verbatim: true`` requires the quote to occur in the text (else ``quote_mismatch``);
    every selector given as a value must select the quote (else ``selector_mismatch``).
    """
    if content is None:
        return SelectorCheck("unavailable", (), ())
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

    checked, issues = [], []
    quote = assertion["quote"]
    exact = quote["exact"]
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
    if not checked:
        return SelectorCheck("unavailable", (), ())
    return SelectorCheck("mismatch" if issues else "match", tuple(checked), tuple(issues))
