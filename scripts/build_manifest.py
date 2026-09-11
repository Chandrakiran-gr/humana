#!/usr/bin/env python3
"""Build corpus/manifest.json, and optionally lock the held-out and transfer splits.

The manifest is Task 1.4: case id, parent case id, procedure, split, scenario
tags, reference version. It also records, per case, the documents in the packet
and a content hash for each, plus a hash of the case's label entry. Those hashes
are what make the split lock mechanical.

    python3 scripts/build_manifest.py            # rebuild the manifest
    python3 scripts/build_manifest.py --lock     # also write corpus/SPLIT_LOCK.json

The lock is deliberately a separate file and a separate flag. Task 1.3 requires
the held-out and transfer splits to be closed after the manual check and not
reopened until Stage 3. A note saying so relies on everyone remembering. A hash
that a test compares against catches the accidental edit instead, which is the
failure mode that actually happens: a global find-and-replace, a reformat, a
well-meant consistency fix applied across all splits at once.

Regenerating the lock requires this flag and should be a deliberate act with a
recorded reason, not a side effect of rebuilding the manifest.
"""

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKED_SPLITS = ("held_out_test", "transfer")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_label_hash(entry: dict) -> str:
    """Hash of the label entry, insensitive to key order and whitespace."""
    return sha256_bytes(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode())


def packet_documents(cases_dir: Path, case_id: str) -> list[dict]:
    d = cases_dir / case_id
    if not d.is_dir():
        return []
    return [
        {"filename": p.name, "sha256": sha256_bytes(p.read_bytes()), "bytes": p.stat().st_size}
        for p in sorted(d.iterdir()) if p.is_file()
    ]


def build(labels: dict, criteria: dict, cases_dir: Path) -> dict:
    sets = {s["procedure_id"]: s for s in criteria["criteria_sets"]}
    entries = []
    for case in labels["cases"]:
        docs = packet_documents(cases_dir, case["case_id"])
        instances = {k: v for k, v in case["expected"].items() if not k.startswith("_")}
        entries.append({
            "case_id": case["case_id"],
            "parent_case_id": case["parent_case_id"],
            "procedure_id": case["procedure_id"],
            "procedure_name": sets[case["procedure_id"]]["procedure_name"],
            "cpt": sets[case["procedure_id"]]["cpt"],
            "split": case["split"],
            "scenario_tags": case["scenario_tags"],
            "reference_version": case["reference_version"],
            "criteria_set_version": case["criteria_set_version"],
            "criterion_instances": len(instances),
            "scorable_instances": sum(
                1 for v in instances.values() if v["clinical_status"] != "NOT_APPLICABLE"),
            "document_count": len(docs),
            "documents": docs,
            "label_sha256": canonical_label_hash(case),
        })
    by_split = {}
    for s in ("development", "held_out_test", "transfer"):
        rows = [e for e in entries if e["split"] == s]
        by_split[s] = {
            "cases": len(rows),
            "independent_cases": sum(1 for e in rows if e["parent_case_id"] is None),
            "documents": sum(e["document_count"] for e in rows),
            "criterion_instances": sum(e["criterion_instances"] for e in rows),
            "scorable_instances": sum(e["scorable_instances"] for e in rows),
            "locked": s in LOCKED_SPLITS,
        }
    return {
        "_meta": {
            "purpose": "Dataset manifest for the synthetic UM evidence corpus. Task 1.4.",
            "generated_by": "scripts/build_manifest.py",
            "regenerate": "python3 scripts/build_manifest.py",
            "note": "Generated from corpus/labels.json and the packets on disk. Do not hand-edit; "
                    "rebuild instead. Document hashes are sha256 of file bytes. The label hash is "
                    "sha256 of the label entry serialised with sorted keys, so it is insensitive to "
                    "key order and formatting but not to content.",
            "reference_version": "1.0",
            "criteria_set_version": criteria["_meta"]["criteria_set_version"],
            "totals": {
                "cases": len(entries),
                "documents": sum(e["document_count"] for e in entries),
                "criterion_instances": sum(e["criterion_instances"] for e in entries),
                "scorable_instances": sum(e["scorable_instances"] for e in entries),
            },
            "by_split": by_split,
        },
        "cases": entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lock", action="store_true",
                    help="Also write corpus/SPLIT_LOCK.json for the held-out and transfer splits.")
    ap.add_argument("--reason", default="",
                    help="Why the lock is being written. Recorded in the lock file.")
    args = ap.parse_args()

    labels = json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text(encoding="utf-8"))
    criteria = json.loads((PROJECT_ROOT / "criteria" / "criteria_sets.json").read_text(encoding="utf-8"))
    cases_dir = PROJECT_ROOT / "corpus" / "cases"

    manifest = build(labels, criteria, cases_dir)
    out = PROJECT_ROOT / "corpus" / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    m = manifest["_meta"]["totals"]
    print(f"[OK] corpus/manifest.json  {m['cases']} cases, {m['documents']} documents, "
          f"{m['criterion_instances']} instances, {m['scorable_instances']} scorable")

    if args.lock:
        lock_path = PROJECT_ROOT / "corpus" / "SPLIT_LOCK.json"
        if lock_path.exists() and not args.reason:
            print("[FAIL] A lock already exists. Rewriting it needs --reason, "
                  "because replacing a lock silently is the thing a lock exists to prevent.")
            return 1
        locked = {
            e["case_id"]: {
                "split": e["split"],
                "label_sha256": e["label_sha256"],
                "documents": {d["filename"]: d["sha256"] for d in e["documents"]},
            }
            for e in manifest["cases"] if e["split"] in LOCKED_SPLITS
        }
        lock_path.write_text(json.dumps({
            "_meta": {
                "purpose": "Content lock for the held-out and transfer splits, per BUILD_SEQUENCE "
                           "Task 1.3. These splits are closed after the manual check and are not "
                           "reopened until Stage 3.",
                "locked_on": date.today().isoformat(),
                "locked_splits": list(LOCKED_SPLITS),
                "reason": args.reason or "Initial lock at the close of Stage 1.",
                "enforced_by": "tests/test_split_lock.py",
                "how_to_change": "Do not edit a locked packet or label. If Stage 3 findings "
                                 "require a change, record why, rerun with --lock and --reason, "
                                 "and disclose in results that the test split was modified after "
                                 "locking and when.",
                "cases": len(locked),
                "documents": sum(len(v["documents"]) for v in locked.values()),
            },
            "locked": locked,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"[OK] corpus/SPLIT_LOCK.json  {len(locked)} cases, "
              f"{sum(len(v['documents']) for v in locked.values())} documents locked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
