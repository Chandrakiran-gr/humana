"""Tests for the startup checks and for keeping credentials out of artifacts.

A version already drifted once: .env.example declared a prompt version that
disagreed with the code. Nothing read it, so nothing broke, which is the part
worth noticing — the drift was invisible precisely because the value was
unused. These tests exist so the next disagreement stops a run instead.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import (  # noqa: E402
    PreflightError, declared_criteria_version, extract, ingest_case,
    load_criteria, preflight, scrub_secrets,
)
from um_evidence.extract import DEFAULT_MODEL  # noqa: E402

CRITERIA = PROJECT_ROOT / "criteria" / "criteria_sets.json"
LABELS = PROJECT_ROOT / "corpus" / "labels.json"
CASES = PROJECT_ROOT / "corpus" / "cases"
GOOD_ENV = {"UM_MODEL": DEFAULT_MODEL}


class DeclaredVersionTests(unittest.TestCase):
    def test_the_repository_declares_one_criteria_version(self) -> None:
        declared = declared_criteria_version(CRITERIA)
        history = json.loads(CRITERIA.read_text())["_meta"]["version_history"]
        self.assertIn(declared, [v["version"] for v in history],
                      "the declared version has no recorded reason")

    def test_disagreeing_declarations_are_an_error(self) -> None:
        """Four places declare this version. They must agree or the run stops."""
        payload = json.loads(CRITERIA.read_text())
        payload["criteria_sets"][1]["criteria_set_version"] = "1.0.0"
        tmp = Path(tempfile.mkdtemp()) / "criteria.json"
        tmp.write_text(json.dumps(payload))
        try:
            with self.assertRaises(PreflightError) as caught:
                declared_criteria_version(tmp)
            self.assertIn("1.0.0", str(caught.exception))
            self.assertIn("total_knee_arthroplasty", str(caught.exception))
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

    def test_a_file_declaring_no_version_is_an_error(self) -> None:
        tmp = Path(tempfile.mkdtemp()) / "criteria.json"
        tmp.write_text(json.dumps({"criteria_sets": [], "_meta": {}}))
        try:
            with self.assertRaises(PreflightError):
                declared_criteria_version(tmp)
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)


class PreflightTests(unittest.TestCase):
    def test_the_repository_as_it_stands_passes(self) -> None:
        checks = preflight(env=GOOD_ENV)
        self.assertTrue(checks.ok, f"unexpected findings: {checks.findings}")
        self.assertEqual(checks.criteria_set_version,
                         declared_criteria_version(CRITERIA))
        self.assertEqual(checks.model, DEFAULT_MODEL)
        self.assertTrue(checks.prompt_version)

    def test_a_missing_model_stops_the_run(self) -> None:
        checks = preflight(env={})
        self.assertFalse(checks.ok)
        self.assertTrue(any("no model configured" in f for f in checks.findings))
        with self.assertRaises(PreflightError):
            checks.raise_if_failed()

    def test_a_model_disagreeing_with_the_code_stops_the_run(self) -> None:
        checks = preflight(env={"UM_MODEL": "claude-opus-5"})
        self.assertFalse(checks.ok)
        self.assertTrue(any("disagrees with the code default" in f
                            for f in checks.findings))

    def test_a_model_override_must_be_deliberate(self) -> None:
        checks = preflight(env={"UM_MODEL": "claude-opus-5"},
                           allow_model_override=True)
        self.assertTrue(checks.ok)
        self.assertEqual(checks.model, "claude-opus-5")

    def test_version_keys_in_the_environment_stop_the_run(self) -> None:
        """Their presence is the defect, whatever value they hold.

        A correct value today is a second source tomorrow. The check is for
        presence so that removing them stays removed.
        """
        for key in ("UM_PROMPT_VERSION", "UM_CRITERIA_SET_VERSION"):
            for value in ("1.1.0", "v1", "wrong"):
                with self.subTest(key=key, value=value):
                    checks = preflight(env={**GOOD_ENV, key: value})
                    self.assertFalse(checks.ok)
                    self.assertTrue(any(key in f for f in checks.findings))

    def test_labels_describing_older_criteria_stop_the_run(self) -> None:
        labels = json.loads(LABELS.read_text())
        labels["cases"][0]["criteria_set_version"] = "1.0.0"
        tmp = Path(tempfile.mkdtemp()) / "labels.json"
        tmp.write_text(json.dumps(labels))
        try:
            checks = preflight(env=GOOD_ENV, labels_path=tmp)
            self.assertFalse(checks.ok)
            self.assertTrue(any("no longer the ones being loaded" in f
                                for f in checks.findings))
        finally:
            shutil.rmtree(tmp.parent, ignore_errors=True)

    def test_findings_accumulate_rather_than_stopping_at_the_first(self) -> None:
        checks = preflight(env={"UM_PROMPT_VERSION": "v1"})
        self.assertGreaterEqual(len(checks.findings), 2,
                                "a missing model and a banned key are both findings")


class SecretHandlingTests(unittest.TestCase):
    FAKE = "sk-ant-api03-" + "A1b2C3d4E5" * 6

    def test_a_key_in_an_error_string_is_redacted(self) -> None:
        text = f"AuthenticationError: invalid x-api-key: {self.FAKE}"
        scrubbed = scrub_secrets(text)
        self.assertNotIn(self.FAKE, scrubbed)
        self.assertIn("sk-ant-<redacted>", scrubbed)
        self.assertIn("AuthenticationError", scrubbed, "context is kept")

    def test_a_transport_error_carrying_a_key_never_reaches_the_run_log(self) -> None:
        """The realistic leak path: the SDK composes the message, not this code."""
        class LeakyClient:
            def complete(self, system, user, **kw):
                raise RuntimeError(f"401 unauthorized for key {SecretHandlingTests.FAKE}")

        run = extract(load_criteria("lumbar_mri"), ingest_case("MRI-005", CASES),
                      LeakyClient(), configuration="A", max_attempts=1)
        serialized = json.dumps(run.as_dict())
        self.assertNotIn(self.FAKE, serialized)
        self.assertIn("sk-ant-<redacted>", serialized)

    def test_env_is_gitignored(self) -> None:
        ignored = (PROJECT_ROOT / ".gitignore").read_text().splitlines()
        self.assertIn(".env", [line.strip() for line in ignored])

    def test_the_example_env_carries_no_value(self) -> None:
        for line in (PROJECT_ROOT / ".env.example").read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY"):
                self.assertEqual(line.strip(), "ANTHROPIC_API_KEY=",
                                 "the template must never carry a key")

    def test_no_key_appears_anywhere_in_tracked_files(self) -> None:
        """Nothing outside .env may contain a credential-shaped string."""
        skip_dirs = {".git", ".venv", "venv", "__pycache__", "runs", "node_modules"}
        offenders = []
        for path in PROJECT_ROOT.rglob("*"):
            if not path.is_file() or path.name == ".env":
                continue
            if set(path.relative_to(PROJECT_ROOT).parts) & skip_dirs:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            # The literal prefix followed by key-shaped characters. This file
            # and the scrubber both mention the prefix, which is why the match
            # requires the shape of an actual key after it.
            if scrub_secrets(text) != text and path.name not in {
                    "test_preflight.py", "extract.py"}:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [], f"credential-shaped strings in {offenders}")

    def test_a_run_artifact_records_settings_but_no_credential(self) -> None:
        from um_evidence import ModelResponse

        class Scripted:
            def complete(self, system, user, **kw):
                return ModelResponse(text='{"results": []}')

        run = extract(load_criteria("lumbar_mri"), ingest_case("MRI-005", CASES),
                      Scripted(), configuration="A", max_attempts=1)
        logged = json.dumps(run.as_dict())
        self.assertIn("model", run.as_dict())
        for banned in ("api_key", "ANTHROPIC_API_KEY", "sk-ant-"):
            self.assertNotIn(banned, logged)


if __name__ == "__main__":
    unittest.main()
