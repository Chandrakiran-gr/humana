#!/usr/bin/env python3
"""Date coherence checks across generated case packets.

Two classes of defect, both of which survived inspection by eye and were found
only by an independent reader:

  FORWARD REFERENCE  A document refers to a dated artifact that did not exist
                     when the document was written. A note dated 06/22 that
                     reviews radiographs dated 06/29 cannot have reviewed them,
                     and any evidence span citing that passage is citing an
                     impossible statement.

  MIXED FORMAT       One packet uses both MM/DD/YYYY and DD/MM/YYYY. Realistic
                     in transferred records, but where a criterion turns on a
                     derived span or on whether a prior study falls inside a
                     window, the two readings give different answers.

Both are reported, not judged. A forward reference to a scheduled future event
is legitimate; a forward reference to something described as already reviewed is
not. Read the output.

    python3 scripts/check_packet_dates.py
    python3 scripts/check_packet_dates.py --case TKA-103

Exit status 0 if nothing is flagged, 1 otherwise.
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Filenames end the stamp with an underscore, which is a word character,
# so the \\b form above never matches them. Anchor instead.
ISO_FILENAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
DOB_LINE = re.compile(r"date of birth|^\s*dob\b", re.I)
# An addendum is added after the report it amends, by definition. From the
# marker onward the effective document date is the addendum's own.
ADDENDUM = re.compile(r"^\s*(addendum|amendment|amended report|revised report)\b", re.I)
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
DAY_MONTH = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b", re.I)
MONTH_YEAR = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.I)

# Phrases that make a later date legitimately forward-looking.
FUTURE_OK = re.compile(
    r"\b(due|review|recheck|repeat|follow[- ]?up|resets?|next|advised at|"
    r"finish\w*|complet\w*|arrange\w*|approv\w*|countersign\w*|"
    r"scheduled|booked|plan year|expires?|valid|reminder|by then|"
    r"before|until|from that date|in \w+ years?)\b", re.I)


def document_date(path: Path, text: str) -> date | None:
    """Prefer the filename stamp; fall back to a dated header, then a letterhead.

    Date-of-birth lines are excluded explicitly. Treating a DOB as the document
    date makes every other date in the file look like a forward reference, which
    is how the first version of this check produced 22 false positives.
    """
    m = ISO_FILENAME.match(path.name)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    for line in text.splitlines():
        if DOB_LINE.search(line):
            continue
        if re.match(r"^\s*(?:date(?:\s*/\s*time)?|exam date|date of (?:service|visit|"
                    r"discharge|evaluation|this report)|printed|reconciled|placed|"
                    r"ordered|entered|submitted|referral date)\s*:", line, re.I):
            found = parse_all(line.split(":", 1)[1])
            if found:
                return found[0][0]

    # Letters carry a bare date near the top instead of a labelled header.
    for line in text.splitlines()[:12]:
        if DOB_LINE.search(line):
            continue
        found = parse_all(line)
        if found and len(line.strip()) < 40:
            return found[0][0]
    return None


def parse_all(text: str) -> list[tuple[date, str]]:
    """Every parseable date in the text, with the literal that produced it."""
    out = []
    for m in ISO.finditer(text):
        try:
            out.append((date(int(m.group(1)), int(m.group(2)), int(m.group(3))), m.group(0)))
        except ValueError:
            pass
    for m in DAY_MONTH.finditer(text):
        day, month = int(m.group(1)), MONTHS[m.group(2).lower()]
        year = re.search(r"\b(20\d{2})\b", text[m.end():m.end() + 12])
        if year:
            try:
                out.append((date(int(year.group(1)), month, day), m.group(0)))
            except ValueError:
                pass
    for m in NUMERIC.finditer(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Read as MM/DD where possible, else DD/MM. Ambiguity is reported
        # separately by the format check; here we only need a usable ordering.
        for mo, da in ((a, b), (b, a)):
            try:
                out.append((date(y, mo, da), m.group(0)))
                break
            except ValueError:
                continue
    return out


def format_evidence(path: Path, text: str) -> dict:
    """What date format this document is forced into, if any."""
    forced = set()
    for m in NUMERIC.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            forced.add("DD/MM")
        elif b > 12 and a <= 12:
            forced.add("MM/DD")
    # A filename stamp plus a matching internal date settles it outright.
    fn = ISO_FILENAME.match(path.name)
    if fn:
        y, mo, da = int(fn.group(1)), int(fn.group(2)), int(fn.group(3))
        for m in NUMERIC.finditer(text):
            a, b, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yy != y:
                continue
            if (a, b) == (mo, da) and mo != da:
                forced.add("MM/DD")
            elif (a, b) == (da, mo) and mo != da:
                forced.add("DD/MM")
    return forced


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases_dir", default="corpus/cases")
    ap.add_argument("--case", default=None)
    args = ap.parse_args()

    root = PROJECT_ROOT / args.cases_dir
    if not root.is_dir():
        print(f"[FAIL] Not found: {root}")
        return 1

    forward, mixed, undated = [], [], []

    for case_dir in sorted(d for d in root.iterdir() if d.is_dir()):
        if args.case and case_dir.name != args.case:
            continue
        formats = {}
        for path in sorted(case_dir.glob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            doc_date = document_date(path, text)
            f = format_evidence(path, text)
            if f:
                formats[path.name] = f
            if doc_date is None:
                undated.append(f"{case_dir.name}/{path.name}")
                continue
            effective = doc_date
            for line_no, line in enumerate(text.splitlines(), start=1):
                if ADDENDUM.match(line):
                    later = [d for d, _ in parse_all(line) if d >= effective]
                    if later:
                        effective = min(later)
                    continue
                if FUTURE_OK.search(line) or DOB_LINE.search(line):
                    continue
                for d, literal in parse_all(line):
                    # Ignore dates of birth and anything long past.
                    if d.year < effective.year - 1:
                        continue
                    if d > effective:
                        forward.append((case_dir.name, path.name, line_no,
                                        effective, literal, line.strip()))

        seen = set().union(*formats.values()) if formats else set()
        if len(seen) > 1:
            mixed.append((case_dir.name, formats))

    print("=== FORWARD REFERENCES (document cites a date later than itself) ===")
    if forward:
        for case, name, ln, dd, lit, line in forward:
            print(f"  {case}/{name}:{ln}  doc dated {dd}, cites {lit}")
            print(f"      | {line[:100]}")
    else:
        print("  none")

    print("\n=== MIXED DATE FORMATS WITHIN A PACKET ===")
    if mixed:
        for case, formats in mixed:
            print(f"  {case}")
            for name, f in sorted(formats.items()):
                print(f"      {name:44} forced {sorted(f)}")
    else:
        print("  none")

    if undated:
        print(f"\n=== NO DOCUMENT DATE FOUND ({len(undated)}) ===")
        print("  Not necessarily wrong, but these are exempt from the forward check.")
        for u in undated:
            print(f"  {u}")

    total = len(forward) + len(mixed)
    print(f"\n{len(forward)} forward reference(s), {len(mixed)} packet(s) with mixed formats.")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
