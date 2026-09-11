"""Enforcement for the held-out and transfer split lock.

BUILD_SEQUENCE Task 1.3 closes the held-out and transfer splits after the manual
check and does not reopen them until Stage 3. A note to that effect relies on
everyone remembering. These tests compare content hashes instead, so the failure
mode that actually happens is caught: a global find-and-replace, a reformat, or
a consistency fix applied across all splits at once during Stage 2.

If one of these fails, the question is not how to make it pass. It is what
changed and whether the change should have been made at all. If the change is
genuinely required, rerun `scripts/build_manifest.py --lock --reason "..."` and
disclose in results that a test split was modified after locking.
"""

import hashlib
import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = PROJECT_ROOT / "corpus" / "labels.json"
LOCK_PATH = PROJECT_ROOT / "corpus" / "SPLIT_LOCK.json"
MANIFEST_PATH = PROJECT_ROOT / "corpus" / "manifest.json"
CASES_DIR = PROJECT_ROOT / "corpus" / "cases"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_label_hash(entry: dict) -> str:
    return hashlib.sha256(
        json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SplitLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lock = load(LOCK_PATH)["locked"]
        self.cases = {c["case_id"]: c for c in load(LABELS_PATH)["cases"]}

    def test_lock_covers_every_locked_split_case(self) -> None:
        should_be_locked = {
            cid for cid, c in self.cases.items()
            if c["split"] in ("held_out_test", "transfer")
        }
        self.assertEqual(set(self.lock), should_be_locked,
                         "a case was added to or removed from a locked split")

    def test_locked_labels_are_unchanged(self) -> None:
        for case_id, entry in self.lock.items():
            with self.subTest(case=case_id):
                self.assertIn(case_id, self.cases, f"{case_id} has been deleted")
                self.assertEqual(
                    canonical_label_hash(self.cases[case_id]), entry["label_sha256"],
                    f"the label for {case_id} has changed since the split was locked")

    def test_locked_packets_are_unchanged(self) -> None:
        for case_id, entry in self.lock.items():
            case_dir = CASES_DIR / case_id
            with self.subTest(case=case_id):
                self.assertTrue(case_dir.is_dir(), f"{case_id} packet is missing")
                on_disk = {p.name for p in case_dir.iterdir() if p.is_file()}
                self.assertEqual(on_disk, set(entry["documents"]),
                                 f"documents added to or removed from {case_id}")
            for filename, expected in entry["documents"].items():
                path = case_dir / filename
                with self.subTest(case=case_id, document=filename):
                    self.assertTrue(path.is_file(), f"{case_id}/{filename} is missing")
                    actual = hashlib.sha256(path.read_bytes()).hexdigest()
                    self.assertEqual(actual, expected,
                                     f"{case_id}/{filename} has changed since locking")


class ManifestTests(unittest.TestCase):
    """Task 1.4. The manifest is generated, so it must still match its sources."""

    def setUp(self) -> None:
        self.manifest = load(MANIFEST_PATH)
        self.cases = {c["case_id"]: c for c in load(LABELS_PATH)["cases"]}

    def test_manifest_covers_every_case(self) -> None:
        self.assertEqual({e["case_id"] for e in self.manifest["cases"]}, set(self.cases))

    def test_required_task_1_4_fields_present(self) -> None:
        for entry in self.manifest["cases"]:
            with self.subTest(case=entry["case_id"]):
                for field in ("case_id", "parent_case_id", "procedure_id",
                              "split", "scenario_tags", "reference_version"):
                    self.assertIn(field, entry)

    def test_manifest_is_not_stale(self) -> None:
        # Hand-editing the manifest, or editing a packet without rebuilding it,
        # both show up here.
        for entry in self.manifest["cases"]:
            case_id = entry["case_id"]
            with self.subTest(case=case_id):
                self.assertEqual(entry["split"], self.cases[case_id]["split"])
                self.assertEqual(entry["scenario_tags"], self.cases[case_id]["scenario_tags"])
                self.assertEqual(entry["label_sha256"],
                                 canonical_label_hash(self.cases[case_id]))
                for doc in entry["documents"]:
                    path = CASES_DIR / case_id / doc["filename"]
                    self.assertTrue(path.is_file(), f"{case_id}/{doc['filename']} missing")
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                                     doc["sha256"],
                                     f"{case_id}/{doc['filename']} changed; rebuild the manifest")

    def test_totals_reconcile(self) -> None:
        t = self.manifest["_meta"]["totals"]
        self.assertEqual(t["cases"], len(self.manifest["cases"]))
        self.assertEqual(t["documents"],
                         sum(e["document_count"] for e in self.manifest["cases"]))
        self.assertEqual(t["criterion_instances"],
                         sum(e["criterion_instances"] for e in self.manifest["cases"]))


if __name__ == "__main__":
    unittest.main()
