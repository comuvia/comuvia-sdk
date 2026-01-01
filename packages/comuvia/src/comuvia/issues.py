"""Issue and refusal types shared by parsing, validation and verification."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class Issue:
    """One named problem. ``pointer`` is an RFC 6901 JSON Pointer ("" is the whole document)."""

    pointer: str
    code: str
    message: str = ""


class RefusalError(ValueError):
    """Input refused: it is invalid and must not be stored or used."""

    def __init__(self, issues: list[Issue] | tuple[Issue, ...]):
        self.issues = tuple(sorted(issues))
        super().__init__("; ".join(f"{i.code} at '{i.pointer}'" for i in self.issues))

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(i.code for i in self.issues)


def pointer_join(pointer: str, token: str | int) -> str:
    text = str(token).replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{text}"
