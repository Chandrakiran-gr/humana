#!/usr/bin/env python3
"""Check that the criteria file's rule prose shares no wording with the packets.

Every string in criteria/criteria_sets.json is sent to the model at runtime,
alongside the packet. If a rule's worked example is quoted verbatim from a
document the model is about to read, the model has been handed the answer next
to the question. That is contamination in production, not only in evaluation:
it would happen on every real request too, and it would make the system look
like it was reasoning when it was matching.

This checks the _meta rule prose only. The criterion text and satisfied_by
fields are exempt, because a criterion about joint space narrowing must be
allowed to use the words joint space narrowing, and a radiology report must be
allowed to contain them.

    python3 scripts/check_criteria_contamination.py
    python3 scripts/check_criteria_contamination.py --n 4

Exit status 0 if no overlap is found, 1 otherwise.
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# _meta keys whose prose is rule guidance rather than clinical vocabulary.
RULE_KEYS = (
    "not_met_bar",
    "addresses_rule",
    "waiver_rule",
    "evidence_requirement_note",
    "audience_warning",
)

# Phrases that are unavoidably shared because they are the vocabulary of the
# domain and of the status names themselves, not examples drawn from a packet.
ALLOWED = {
    "range of motion", "physical therapy", "conservative management",
    "low back pain", "prior authorization", "review of systems",
}


# A clinical literal: a measurement, grade, or coded value. These are the
# highest-risk collisions, because a number quoted from a packet into a rule is
# almost never a coincidence, and an n-gram window will not see it.
LITERAL = re.compile(r"\b\d+(?:[./+]\d+)+\b|\b\d+\.\d+\b")

# Short clinical phrases are the other high-risk shape. A rule that says "no
# effusion" while nine packets say "no effusion" is contaminated even though
# the surrounding words differ, so a long window misses it entirely. That is
# the exact defect this script was written for, and the first version of it
# could not detect it.
CLINICAL_HEAD = re.compile(
    r"\b(?:no|absent|normal|negative|denies|nil)\s+([a-z]+(?:\s+[a-z]+)?)", re.I)

# Words that follow "no" in ordinary English rather than in a clinical negation.
# Without these the check fires on prose like "no reason to continue".
NON_CLINICAL = {
    "reason", "other", "further", "longer", "need", "doubt", "question",
    "more", "one", "way", "such", "amount", "claim", "run", "point", "sense",
    "record", "records", "entries", "part", "single", "label", "rule", "route",
}


def ngrams(text: str, n: int) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def literals(text: str) -> set[str]:
    return set(LITERAL.findall(text))


def clinical_negations(text: str) -> set[str]:
    """Emit both the one-word and two-word form of each negation.

    "no effusion appreciated" and "no effusion on examination" must intersect
    on "no effusion". Emitting only the greedy match means they never do, which
    is how the second version of this script still missed the defect it exists
    to catch.
    """
    out = set()
    for m in CLINICAL_HEAD.finditer(text):
        head = m.group(0).split()[0].lower()
        tail = m.group(1).lower().split()
        if tail and tail[0] in NON_CLINICAL:
            continue
        if tail:
            out.add(f"{head} {tail[0]}")
        if len(tail) > 1:
            out.add(f"{head} {tail[0]} {tail[1]}")
    return out


def contaminating_phrases(authored_text: str, cases_dir: Path,
                          n: int = 5) -> dict[str, list[str]]:
    """Phrases shared between authored prose and any packet, with where they appear.

    Importable so that the same comparison can be run against a string that was
    never on disk. What reaches the model at Step 3 is an assembled prompt, not
    criteria_sets.json, and an assembly step can introduce wording that no check
    of the source file would ever see. tests/test_extract.py runs this against
    the exact authored text of the prompt for that reason.
    """
    text_grams = ngrams(authored_text, n)
    text_literals = literals(authored_text)
    text_negations = clinical_negations(authored_text)

    hits: dict[str, list[str]] = {}
    for path in sorted(Path(cases_dir).rglob("*")):
        if not path.is_file():
            continue
        packet = path.read_text(encoding="utf-8", errors="replace")
        shared = text_grams & ngrams(packet, n)
        shared |= text_literals & literals(packet)
        shared |= text_negations & clinical_negations(packet)
        shared = {s for s in shared if not any(a in s for a in ALLOWED)}
        for s in shared:
            hits.setdefault(s, []).append(f"{path.parent.name}/{path.name}")
    return hits


def rule_prose(criteria_path: Path) -> str:
    criteria = json.loads(Path(criteria_path).read_text(encoding="utf-8"))
    meta = criteria["_meta"]
    return " ".join(str(meta[k]) for k in RULE_KEYS if k in meta)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--criteria", default="criteria/criteria_sets.json")
    ap.add_argument("--cases_dir", default="corpus/cases")
    ap.add_argument("--n", type=int, default=5,
                    help="Overlap length in words. Shorter is stricter.")
    args = ap.parse_args()

    cases_dir = PROJECT_ROOT / args.cases_dir
    hits = contaminating_phrases(
        rule_prose(PROJECT_ROOT / args.criteria), cases_dir, args.n)

    print(f"Comparing {len(RULE_KEYS)} rule strings against "
          f"{sum(1 for p in cases_dir.rglob('*') if p.is_file())} documents, "
          f"{args.n}-word overlap, plus numeric literals and short clinical negations.\n")
    if hits:
        print(f"[FAIL] {len(hits)} shared phrase(s). The model would see these twice, "
              f"once as a rule and once as data:\n")
        for phrase, where in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            shown = ", ".join(sorted(set(where))[:4])
            more = "" if len(set(where)) <= 4 else f" and {len(set(where)) - 4} more"
            print(f'  "{phrase}"')
            print(f"      in {shown}{more}")
        return 1

    print("[OK] No rule prose appears verbatim in any packet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
