"""Canonical text and the offset map back to the raw source.

The decision and its reasoning are in docs/SPAN_REPRESENTATION.md. This module
implements it and nothing else. Three normalizations, in order: Unicode NFC,
line endings to LF, runs of whitespace collapsed to a single space with the
document trimmed.

No character that is not whitespace is added, removed, or changed. The tests
assert that directly rather than trusting the implementation to have stayed
honest.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalText:
    """Normalized text plus the map from canonical index to raw index.

    `offsets[i]` is the index in `raw` of the character that produced
    `canonical[i]`. It has exactly `len(canonical) + 1` entries: the final entry
    is the raw index just past the last canonical character, so that a
    half-open canonical span `[a, b)` projects to the half-open raw span
    `[offsets[a], offsets[b])` without a special case at the end.
    """

    raw: str
    canonical: str
    offsets: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.offsets) != len(self.canonical) + 1:
            raise ValueError(
                f"offset map has {len(self.offsets)} entries for "
                f"{len(self.canonical)} characters; expected "
                f"{len(self.canonical) + 1}")

    def to_raw(self, start: int, end: int) -> tuple[int, int]:
        """Project a canonical span back onto the raw text."""
        if not 0 <= start <= end <= len(self.canonical):
            raise ValueError(
                f"span [{start}, {end}) outside canonical text of length "
                f"{len(self.canonical)}")
        return self.offsets[start], self.offsets[end]

    def raw_slice(self, start: int, end: int) -> str:
        """The original text underlying a canonical span, whitespace and all."""
        a, b = self.to_raw(start, end)
        return self.raw[a:b]

    def find_all(self, needle: str) -> list[tuple[int, int]]:
        """Every occurrence of a canonicalized needle, as canonical spans.

        Returns all occurrences rather than the first. A quote appearing twice
        in one document is the case that makes span-based citation necessary in
        the first place, so silently taking the first match would defeat the
        representation.
        """
        target = canonicalize(needle).canonical
        if not target:
            return []
        out: list[tuple[int, int]] = []
        i = self.canonical.find(target)
        while i != -1:
            out.append((i, i + len(target)))
            i = self.canonical.find(target, i + 1)
        return out


def canonicalize(raw: str) -> CanonicalText:
    """Build canonical text and its offset map in a single pass.

    The map is built here rather than reconstructed later. Reconstructing it
    would mean re-deriving the normalization somewhere else, and the two copies
    would drift the first time either changed.
    """
    # NFC first. Composition can change length, so the map is built against the
    # composed form and `raw` is stored composed to keep indices meaningful.
    composed = unicodedata.normalize("NFC", raw)
    composed = composed.replace("\r\n", "\n").replace("\r", "\n")

    chars: list[str] = []
    offsets: list[int] = []
    i = 0
    n = len(composed)

    # Leading whitespace is dropped entirely.
    while i < n and composed[i].isspace():
        i += 1

    pending_space_at: int | None = None
    while i < n:
        ch = composed[i]
        if ch.isspace():
            # Remember where the run started; emit at most one space, and only
            # if a non-space character follows. That drops trailing whitespace
            # without needing a second pass.
            if pending_space_at is None:
                pending_space_at = i
            i += 1
            continue
        if pending_space_at is not None:
            chars.append(" ")
            offsets.append(pending_space_at)
            pending_space_at = None
        chars.append(ch)
        offsets.append(i)
        i += 1

    # One past the last emitted character, so half-open spans project cleanly.
    offsets.append(offsets[-1] + 1 if offsets else 0)
    return CanonicalText(raw=composed, canonical="".join(chars),
                         offsets=tuple(offsets))
