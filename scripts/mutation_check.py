#!/usr/bin/env python3
"""Verify that the test suite can actually fail.

Why this exists
---------------
During Stage 1, four of four checkers written for this corpus passed on their
first run while the defect they were written to catch was present. Each was
written by the author whose errors it was meant to find, which is the same
reason it could not find them. The rule adopted afterwards is that no check is
trusted until it has been shown to fail on a real instance of the defect it
targets.

A passing test suite is evidence of nothing on its own. This script supplies the
missing half: it introduces one real defect at a time into the source, runs the
single test written to catch that defect, and confirms the test fails. A
mutation that survives is a test that does not test anything.

The source file is restored after every mutation, including on exception, and
the suite is re-run clean at the end to prove nothing was left behind.

Scope
-----
This is deliberately not general-purpose mutation testing. Every mutation is a
hand-written defect that a reviewer would recognise as plausible, paired with
the test that should object to it. The pairing is the point: it documents which
test is load-bearing for which behaviour.

Usage
-----
    python3 scripts/mutation_check.py            # all mutations
    python3 scripts/mutation_check.py --list     # show them without running
    python3 scripts/mutation_check.py -k span    # only matching labels

Exit status is 0 only if every mutation was caught and the suite is green
afterwards.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    label: str          # the defect, described as a reviewer would describe it
    relpath: str        # file to mutate
    old: str            # exact anchor, must occur exactly once
    new: str            # the defect
    caught_by: str      # unittest -k pattern for the test that must fail


MUTATIONS: tuple[Mutation, ...] = (
    # --- Step 2: document outcomes -------------------------------------------
    Mutation(
        "scanned PDF reported as EMPTY rather than NO_TEXT_LAYER",
        "um_evidence/ingest.py",
        '        return ("", DocumentOutcome.NO_TEXT_LAYER,',
        '        return ("", DocumentOutcome.EMPTY,',
        "test_scanned_pdf_is_no_text_layer_not_empty"),
    Mutation(
        "over-limit document keeps its text, inviting silent truncation",
        "um_evidence/ingest.py",
        "        doc.text = None\n    return doc",
        "        pass\n    return doc",
        "test_oversized_input_is_flagged_and_not_truncated"),
    Mutation(
        "input-limit gate disabled entirely",
        "um_evidence/ingest.py",
        "    if per_document_token_limit is not None and "
        "doc.estimated_tokens > per_document_token_limit:",
        "    if False:",
        "test_oversized_input_is_flagged_and_not_truncated"),

    # --- Step 2: packet status ------------------------------------------------
    Mutation(
        "packet with no usable document downgraded to PARTIAL",
        "um_evidence/ingest.py",
        "        if not self.usable:\n            return ProcessingStatus.FAILED",
        "        if not self.usable:\n            return ProcessingStatus.PARTIAL",
        "test_packet_status_reflects_document_outcomes"),
    Mutation(
        "over-limit document does not fail the packet",
        "um_evidence/ingest.py",
        "        if any(d.outcome is DocumentOutcome.INPUT_LIMIT_EXCEEDED "
        "for d in self.documents):",
        "        if False:",
        "test_packet_status_reflects_document_outcomes"),

    # --- Citability -----------------------------------------------------------
    Mutation(
        "unciteable document returns a span anyway",
        "um_evidence/ingest.py",
        '        if self.text is None:\n            raise ValueError(\n'
        '                f"{self.document_id} has no canonical text '
        '({self.outcome.value}); "\n'
        '                f"it cannot be cited")',
        "        if self.text is None:\n            return Span("
        "self.document_id, self.content_sha256, start, end)",
        "test_a_document_without_text_cannot_be_cited"),
    Mutation(
        "packet-level lookup searches only the first usable document",
        "um_evidence/ingest.py",
        "        return [s for d in self.usable for s in d.locate(quote)]",
        "        return self.usable[0].locate(quote) if self.usable else []",
        "test_a_real_copy_forward_block_resolves_to_two_documents"),

    # --- Independent verification of identity ---------------------------------
    Mutation(
        "manifest check can never disagree",
        "um_evidence/ingest.py",
        "    if mismatches or missing or extra:",
        "    if False:",
        "test_the_manifest_check_can_actually_fail"),

    # --- Span representation --------------------------------------------------
    Mutation(
        "find_all returns only the first occurrence",
        "um_evidence/spans.py",
        "        i = self.canonical.find(target)\n        while i != -1:",
        "        i = self.canonical.find(target)\n        while i != -1 and not out:",
        "test_repeated_quote_yields_distinct_spans"),
    Mutation(
        "only literal spaces are collapsed, so line breaks survive canonicalization",
        "um_evidence/spans.py",
        "        if ch.isspace():",
        '        if ch == " ":',
        "test_quote_wrapped_across_a_line_break_still_matches"),

    # --- Step 3: the two configurations must not drift apart ------------------
    Mutation(
        "the exception pathway is sent to Baseline A but not to Candidate B",
        "um_evidence/prompts.py",
        "    if criteria_set.has_exception_pathway and criteria_set.exception_note:",
        "    if len(criterion_ids) > 1 and criteria_set.exception_note:",
        "test_the_two_configurations_send_the_same_prompt"),
    Mutation(
        "a packet sentence is planted in the system prompt",
        "um_evidence/prompts.py",
        "OUTPUT\n\nReturn a single JSON object and nothing else.",
        "OUTPUT\n\nFor example: she points to the right lower lumbar area and "
        "says it catches when she gets up from the couch.\n\n"
        "Return a single JSON object and nothing else.",
        "test_no_authored_prompt_text_appears_in_any_packet"),
    Mutation(
        "the prompt stops forbidding capitalisation changes",
        "um_evidence/prompts.py",
        "**Do not adjust capitalisation to make a quote read as a sentence.**",
        "Quotes may begin wherever is convenient.",
        "test_the_prompt_forbids_adjusting_capitalisation"),
    Mutation(
        "the contamination scope is emptied, making its check vacuous",
        "um_evidence/prompts.py",
        "        text = self.authored_text\n"
        "        for exempt in self.exempt_text:\n"
        "            text = text.replace(exempt, \" \")\n"
        "        return text",
        "        return \"\"",
        "test_the_checked_scope_is_not_empty"),

    # --- Step 3: a failure must never become a finding ------------------------
    Mutation(
        "a rejected response is recorded as AMBIGUOUS instead of no status",
        "um_evidence/extract.py",
        "            criterion_id=criterion_id, clinical_status=None,\n"
        "            processing_status=ProcessingStatus.FAILED,\n"
        "            reason_codes=[ReasonCode.PROCESSING_ERROR], detail=detail,\n"
        "            failure_kind=FailureKind.CONTRACT_REJECTION,",
        "            criterion_id=criterion_id,\n"
        "            clinical_status=ClinicalStatus.AMBIGUOUS,\n"
        "            processing_status=ProcessingStatus.FAILED,\n"
        "            reason_codes=[ReasonCode.PROCESSING_ERROR], detail=detail,\n"
        "            failure_kind=FailureKind.CONTRACT_REJECTION,",
        "test_invalid_content_fails_without_inventing_a_status"),
    Mutation(
        "an unreadable packet is sent to the model anyway",
        "um_evidence/extract.py",
        "    if packet.processing_status is ProcessingStatus.FAILED:",
        "    if False:",
        "test_a_failed_packet_is_never_sent_to_the_model"),
    Mutation(
        "NOT_MET is accepted with nothing cited",
        "um_evidence/extract.py",
        "    if status == ClinicalStatus.NOT_MET.value and not evidence:",
        "    if False:",
        "test_invalid_content_fails_without_inventing_a_status"),
    Mutation(
        "reason codes reserved for later steps are accepted from the extractor",
        "um_evidence/extract.py",
        "        if code not in EXTRACTOR_REASON_CODES:",
        "        if False:",
        "test_invalid_content_fails_without_inventing_a_status"),
    Mutation(
        "a criterion the model skipped is silently dropped",
        "um_evidence/extract.py",
        "            for cid in prompt.criterion_ids\n        ]\n        return results",
        "            for cid in entries\n        ]\n        return results",
        "test_a_criterion_omitted_by_the_model_is_not_silently_dropped"),
    Mutation(
        "a response naming a criterion that was not asked about is accepted",
        "um_evidence/extract.py",
        "        if cid not in expected_ids:",
        "        if False:",
        "test_rejects_malformed_input_rather_than_repairing_it"),
    Mutation(
        "raw output is discarded instead of retained",
        "um_evidence/extract.py",
        "        run.attempts.append(attempt)",
        "        pass",
        "test_raw_output_is_retained_even_when_rejected"),

    # --- Startup checks: one fact, one source --------------------------------
    Mutation(
        "disagreeing criteria versions are accepted, first one wins",
        "um_evidence/preflight.py",
        "    if len(distinct) != 1:",
        "    if False:",
        "test_disagreeing_declarations_are_an_error"),
    Mutation(
        "a model disagreeing with the code default is accepted silently",
        "um_evidence/preflight.py",
        "    elif resolved_model != DEFAULT_MODEL and not allow_model_override:",
        "    elif False:",
        "test_a_model_disagreeing_with_the_code_stops_the_run"),
    Mutation(
        "version keys are readmitted to the environment",
        "um_evidence/preflight.py",
        "        if env.get(key):",
        "        if False:",
        "test_version_keys_in_the_environment_stop_the_run"),
    Mutation(
        "labels describing superseded criteria no longer stop a run",
        "um_evidence/preflight.py",
        "    if stale:",
        "    if False:",
        "test_labels_describing_older_criteria_stop_the_run"),
    Mutation(
        "findings are collected but never raised",
        "um_evidence/preflight.py",
        "        if self.findings:\n            raise PreflightError(",
        "        if False:\n            raise PreflightError(",
        "test_a_missing_model_stops_the_run"),

    # --- Credentials must not reach an artifact ------------------------------
    Mutation(
        "a key in a transport error is written to the run log verbatim",
        "um_evidence/extract.py",
        "                       error=scrub_secrets(f\"{type(exc).__name__}: {exc}\"),",
        "                       error=f\"{type(exc).__name__}: {exc}\",",
        "test_a_transport_error_carrying_a_key_never_reaches_the_run_log"),
    Mutation(
        "a request the server already refused is retried anyway",
        "um_evidence/extract.py",
        "            if not attempt.retryable:",
        "            if False:",
        "test_a_request_the_server_refuses_is_not_retried"),
    Mutation(
        "every failure is treated as permanent, so nothing is ever retried",
        "um_evidence/extract.py",
        "    if isinstance(status, int):\n"
        "        return status not in NON_RETRYABLE_STATUS\n"
        "    return True",
        "    return False",
        "test_a_transient_failure_is_retried"),
    Mutation(
        "a deprecated sampling parameter is sent on every call",
        "um_evidence/extract.py",
        "DEFAULT_TEMPERATURE: float | None = None",
        "DEFAULT_TEMPERATURE: float | None = 0.0",
        "test_temperature_is_not_sent_unless_asked_for"),
    # --- Step 4: a citation must resolve to a location ------------------------
    Mutation(
        "a quote resolving in several places is accepted as a citation",
        "um_evidence/verify.py",
        "        elif len(spans) > 1:",
        "        elif False:",
        "test_a_quote_repeated_inside_one_document_is_rejected"),
    Mutation(
        "a conclusion that lost all its support keeps its status",
        "um_evidence/verify.py",
        "    out.downgraded = True\n"
        "    out.clinical_status = ClinicalStatus.AMBIGUOUS",
        "    out.downgraded = True",
        "test_a_met_losing_all_support_is_downgraded"),
    Mutation(
        "a partially unverified conclusion is left standing",
        "um_evidence/verify.py",
        "    if not out.verified_evidence:\n"
        "        out.downgrade_reason = (",
        "    if True:\n"
        "        out.downgrade_reason = (",
        "test_a_met_losing_part_of_its_support_is_downgraded"),
    Mutation(
        "a citation naming a document that was never read is accepted",
        "um_evidence/verify.py",
        "        except KeyError:",
        "        except ZeroDivisionError:",
        "test_a_citation_naming_an_unknown_document_is_rejected"),

    # --- Step 5: the verifier must not see the record -------------------------
    Mutation(
        "the support verifier is handed the packet",
        "um_evidence/verify.py",
        '        system=SUPPORT_SYSTEM, criteria_block=body, record_block="",',
        "        system=SUPPORT_SYSTEM, criteria_block=body,\n"
        "        record_block=chr(10).join(d.canonical for d in result.evidence[:0]) or "
        '"<record>leaked</record>",',
        "test_the_verifier_never_receives_the_packet"),
    Mutation(
        "an inconclusive support check is treated as a failure",
        "um_evidence/verify.py",
        '        if outcome == "UNSUPPORTED" and result.clinical_status in DETERMINATE:',
        '        if outcome != "SUPPORTED" and result.clinical_status in DETERMINATE:',
        "test_inconclusive_changes_nothing_and_is_recorded"),
    Mutation(
        "a verifier outage rewrites the clinical status",
        "um_evidence/verify.py",
        '    result.support_outcome = "FAILED"',
        '    result.clinical_status = ClinicalStatus.AMBIGUOUS\n'
        '    result.support_outcome = "FAILED"',
        "test_a_failed_check_does_not_touch_the_clinical_status"),
    Mutation(
        "support verification is spent on results that cite nothing",
        "um_evidence/verify.py",
        "    if not result.verified_evidence:\n        return False",
        "    if False:\n        return False",
        "test_a_result_with_nothing_cited_is_skipped"),
    Mutation(
        "an UNSUPPORTED verdict can overturn a correct abstention",
        "um_evidence/verify.py",
        '        if outcome == "UNSUPPORTED" and result.clinical_status in DETERMINATE:',
        '        if outcome == "UNSUPPORTED":',
        "test_an_unsupported_verdict_cannot_overturn_an_abstention"),
    Mutation(
        "a malformed verdict is accepted",
        "um_evidence/verify.py",
        "    if outcome not in VALID_SUPPORT_OUTCOMES:",
        "    if False:",
        "test_a_malformed_verdict_is_rejected"),

    # --- The checker battery itself ------------------------------------------
    # Five of five checkers written for this project passed on their first run
    # while the defect they targeted was present. These mutations exist so that
    # each check has been shown to fail rather than assumed to work.
    Mutation(
        "validate_labels stops enforcing MISSING_EVIDENCE against zero units",
        "scripts/validate_labels.py",
        '        check(("MISSING_EVIDENCE" in reason_codes) == '
        '(units == 0 and status == "AMBIGUOUS"),',
        '        check(True or ("MISSING_EVIDENCE" in reason_codes) == '
        '(units == 0 and status == "AMBIGUOUS"),',
        "test_validate_labels_catches_a_broken_invariant"),
    Mutation(
        "the unit-count floor ignores per-modality multiplication",
        "scripts/check_unit_counts.py",
        "        return n * 2, f\"{n} modalit{'y' if n == 1 else 'ies'}, "
        "each needing an attempt and an outcome\"",
        "        return 2, f\"{n} modalit{'y' if n == 1 else 'ies'}, "
        "each needing an attempt and an outcome\"",
        "test_unit_counts_catches_an_undercount"),
    Mutation(
        "the unit-count check forgets that a one-passage branch exists",
        "scripts/check_unit_counts.py",
        "    if SINGLE_PASSAGE_BRANCH.search(satisfied_by):\n"
        "        return 1, \"has a branch satisfiable by one passage\"",
        "    if False:\n"
        "        return 1, \"has a branch satisfiable by one passage\"",
        "test_unit_counts_does_not_flag_a_single_passage_branch"),
    Mutation(
        "instances may carry no acceptable evidence at all",
        "scripts/validate_labels.py",
        '            check(isinstance(acceptable, dict),',
        '            check(True or isinstance(acceptable, dict),',
        "test_validate_labels_catches_a_missing_acceptable_set"),
    Mutation(
        "the acceptable set may disagree with evidence_units_required",
        "scripts/validate_labels.py",
        "                check(len(unit_list) == units,",
        "                check(True or len(unit_list) == units,",
        "test_validate_labels_catches_a_unit_count_disagreement"),
    Mutation(
        "a contradiction may cite only one side",
        "scripts/validate_labels.py",
        '                    check(roles == {"supporting", "contradicting"},',
        '                    check(True or roles == {"supporting", "contradicting"},',
        "test_validate_labels_catches_a_one_sided_contradiction"),
    Mutation(
        "the lexical check collects no constrained instances",
        "scripts/check_lexical_constraints.py",
        "            terms = expectation.get(\"prohibited_terms\")\n"
        "            if not terms:\n                continue",
        "            terms = expectation.get(\"prohibited_terms\")\n"
        "            if terms or not terms:\n                continue",
        "test_lexical_constraints_catches_a_planted_term"),
    Mutation(
        "forward date references are collected but never recorded",
        "scripts/check_packet_dates.py",
        "                    if d > effective:\n"
        "                        forward.append((case_dir.name, path.name, line_no,",
        "                    if False:\n"
        "                        forward.append((case_dir.name, path.name, line_no,",
        "test_packet_dates_catches_a_forward_reference"),

    # --- Task 2.4: the scorer, which is the sixth checker ---------------------
    Mutation(
        "recall counts a unit as recovered whether or not it was cited",
        "um_evidence/score.py",
        "        if any(cites_same_passage(r, t) for r in located for t in targets):",
        "        if True:",
        "test_recovering_one_of_two_units_scores_one_of_two"),
    Mutation(
        "every returned span is accepted, so precision can never fall",
        "um_evidence/score.py",
        "        if any(cites_same_passage(rng, t) for t in acceptable):",
        "        if True:",
        "test_an_unenumerated_span_is_a_precision_miss_and_is_named"),
    Mutation(
        "repeated citations of one passage are counted twice",
        "um_evidence/score.py",
        "        if any(_overlaps(rng, s) for s in seen):\n            continue",
        "        if False:\n            continue",
        "test_repeated_spans_are_deduplicated"),
    Mutation(
        "an unverified span is treated as accepted evidence",
        "um_evidence/score.py",
        "        if not item.verified or rng[1] < 0:\n            continue",
        "        if False:\n            continue",
        "test_an_unverified_span_counts_against_precision"),
    Mutation(
        "status agreement is computed as if nothing ever disagreed",
        "um_evidence/score.py",
        "    score.status_match = (score.returned_status == score.reference_status)",
        "    score.status_match = True",
        "test_a_wrong_status_does_not_match"),
    Mutation(
        "contract rejections are scored as ordinary status errors",
        "um_evidence/score.py",
        "        return self.failure_kind is not FailureKind.CONTRACT_REJECTION",
        "        return True",
        "test_a_contract_rejection_leaves_the_status_denominator"),
    Mutation(
        "waived instances are scored like any other",
        "um_evidence/score.py",
        '        if expectation["clinical_status"] == "NOT_APPLICABLE":\n            continue',
        '        if False:\n            continue',
        "test_not_applicable_instances_are_excluded"),
    Mutation(
        "a critical error direction is printed as a rate",
        "um_evidence/score.py",
        '        lines.append(f"  {label}: {len(group)}")',
        '        lines.append(f"  {label}: {len(group)} "\n'
        '                     f"({len(group) / max(len(score.scored), 1):.1%})")',
        "test_no_rate_is_printed_for_either_critical_direction"),
    Mutation(
        "a metric prints a percentage without its counts",
        "um_evidence/score.py",
        '        return (f"{self.name}: {self.numerator} of {self.denominator} "\n'
        '                f"({self.value:.1%})")',
        '        return f"{self.name}: {self.value:.1%}"',
        "test_the_report_never_prints_a_bare_percentage"),

    Mutation(
        "a truncated response is retried and its cause hidden",
        "um_evidence/extract.py",
        '    if response.stop_reason == "max_tokens":',
        "    if False:",
        "test_a_truncated_response_says_so_and_is_not_retried"),
    Mutation(
        "a returned span must match the reference boundaries exactly",
        "um_evidence/score.py",
        "    overlap = min(returned[2], reference[2]) - max(returned[1], reference[1])\n"
        "    shorter = min(ref_len, ret_len)\n"
        "    return shorter > 0 and overlap / shorter >= MIN_OVERLAP",
        "    return returned == reference",
        "test_a_wider_quote_cites_the_same_passage"),
    Mutation(
        "any overlap counts, so one document-sized span scores everything",
        "um_evidence/score.py",
        "    if ret_len > max(ref_len * MAX_SPAN_FACTOR, ref_len + MAX_SPAN_SLACK):\n"
        "        return False",
        "    if False:\n        return False",
        "test_a_document_sized_span_does_not_recover_everything"),

    # --- Task 3.3: interface and correction store ---------------------------
    Mutation(
        "the scorer gains access to the correction store",
        "um_evidence/score.py",
        "from .results import ClinicalStatus, FailureKind, ProcessingStatus",
        "from . import corrections  # noqa\nfrom .results import ClinicalStatus, FailureKind, ProcessingStatus",
        "test_the_scorer_does_not_import_corrections"),
    Mutation(
        "a correction may be recorded with no reason",
        "um_evidence/corrections.py",
        '    if not reason.strip():',
        '    if False:',
        "test_a_reason_is_required"),
    Mutation(
        "AMBIGUOUS is rendered the same as NOT_MET",
        "app.py",
        '    "AMBIGUOUS": ("Insufficient or conflicting evidence", "#1f4e79", "#e8f0fa"),',
        '    "AMBIGUOUS": ("Potential mismatch requiring review", "#8a4b00", "#fdf0e2"),',
        "test_ambiguous_and_not_met_render_differently"),
    Mutation(
        "the interface stops saying which mode it is showing",
        "app.py",
        'f"**Showing a recorded run.** Artifact `{run_path.name}`, generated "',
        'f"Artifact `{run_path.name}`, generated "',
        "test_the_mode_is_stated_not_inferred"),

    Mutation(
        "the scrubber matches nothing",
        "um_evidence/extract.py",
        '_SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\\-]{8,}")',
        '_SECRET = re.compile(r"(?!x)x")',
        "test_a_key_in_an_error_string_is_redacted"),
)


def run_tests(pattern: str | None = None) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "unittest"]
    if pattern:
        cmd += ["-k", pattern]
    cmd += ["discover", "-s", "tests"]
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    return proc.returncode == 0, proc.stderr


def apply_and_check(mutation: Mutation) -> tuple[bool, str]:
    """Apply one defect, run its test, restore the file. True if caught."""
    path = PROJECT_ROOT / mutation.relpath
    original = path.read_text(encoding="utf-8")

    occurrences = original.count(mutation.old)
    if occurrences != 1:
        return False, (f"anchor occurs {occurrences} times in {mutation.relpath}; "
                       f"it must occur exactly once. The source has moved and this "
                       f"mutation is no longer testing what it claims.")
    try:
        path.write_text(original.replace(mutation.old, mutation.new), encoding="utf-8")
        passed, _ = run_tests(mutation.caught_by)
    finally:
        path.write_text(original, encoding="utf-8")

    if passed:
        return False, f"{mutation.caught_by} still passed with the defect present"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true",
                        help="print the mutations without running them")
    parser.add_argument("-k", dest="filter", default="",
                        help="only run mutations whose label contains this text")
    args = parser.parse_args()

    selected = [m for m in MUTATIONS if args.filter.lower() in m.label.lower()]
    if not selected:
        print(f"No mutation label matches {args.filter!r}.")
        return 1

    if args.list:
        for m in selected:
            print(f"{m.label}\n    {m.relpath} -> {m.caught_by}\n")
        return 0

    print(f"Introducing {len(selected)} defect(s), one at a time.\n")
    survived = []
    for m in selected:
        caught, detail = apply_and_check(m)
        if caught:
            print(f"  caught       {m.label}\n               by {m.caught_by}")
        else:
            survived.append(m)
            print(f"  SURVIVED     {m.label}\n               {detail}")

    print()
    clean, stderr = run_tests()
    if not clean:
        print("Suite is NOT green after restoring the source. Check for a leftover "
              "mutation before trusting anything above.")
        print(stderr[-2000:])
        return 1
    print("Source restored, full suite green.")

    if survived:
        print(f"\n{len(survived)} mutation(s) survived. Those behaviours are "
              f"unverified: a test exists but does not object to the defect.")
        return 1
    print(f"All {len(selected)} mutation(s) caught.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
