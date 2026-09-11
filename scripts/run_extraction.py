#!/usr/bin/env python3
"""Run Step 3 against one case and write the run log.

This is the first thing in the project that spends money, so it runs one case
at a time and says what it is about to do before doing it.

    python3 scripts/run_extraction.py MRI-005 --dry-run     # assemble only
    python3 scripts/run_extraction.py MRI-005               # Baseline A
    python3 scripts/run_extraction.py MRI-005 --config B    # Candidate B

`--dry-run` builds the prompt, prints its size and the token estimate, and
makes no call. Run it first.

Held-out and transfer cases are refused unless `--unlock` is passed. Spec
Section 7 assigns splits before tuning, and a held-out case looked at during
development is no longer held out. The flag exists so that using one is a
deliberate act with a name, rather than a typo in a case id.

The run log goes to runs/, which is gitignored. Results that back a reported
finding belong in evals/results/ and are tracked. Spec Section 11 lists what a
run must record: case and split, document hashes, criteria version, prompt and
model versions, settings, stage outcomes, tokens, timing, retries, output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# The key lives in .env, which is gitignored. Loaded here rather than in the
# package so that importing um_evidence never reaches for a credential.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:  # python-dotenv is in requirements.txt but may not be installed
    pass

from um_evidence import (  # noqa: E402
    AnthropicClient, PreflightError, ProcessingStatus, build_extraction_prompt,
    extract, ingest_case, load_criteria, preflight, verify_run,
)
from um_evidence.extract import (  # noqa: E402
    DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, MAX_ATTEMPTS,
)

CASES = PROJECT_ROOT / "corpus" / "cases"
LABELS = PROJECT_ROOT / "corpus" / "labels.json"
LOCKED_SPLITS = {"held_out_test", "transfer"}


def case_record(case_id: str) -> dict:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    for case in labels["cases"]:
        if case["case_id"] == case_id:
            return case
    raise SystemExit(f"{case_id} is not in corpus/labels.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("case_id")
    ap.add_argument("--config", choices=("A", "B"), default="A")
    ap.add_argument("--model", default=os.environ.get("UM_MODEL", DEFAULT_MODEL))
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble the prompt and stop, making no call")
    ap.add_argument("--unlock", action="store_true",
                    help="permit a held-out or transfer case")
    ap.add_argument("--allow-model-override", action="store_true",
                    help="permit a model differing from the code default")
    ap.add_argument("--no-support", action="store_true",
                    help="run Step 4 only; skip the support-verification calls")
    args = ap.parse_args()

    # Before anything else, including the dry run. A dry run that assembles a
    # prompt under a configuration the real run would reject is misleading.
    try:
        checks = preflight(model=args.model,
                           allow_model_override=args.allow_model_override
                           ).raise_if_failed()
    except PreflightError as exc:
        print(exc)
        return 1
    print(f"preflight: model={checks.model} prompt={checks.prompt_version} "
          f"criteria={checks.criteria_set_version}")

    record = case_record(args.case_id)
    split = record["split"]
    if split in LOCKED_SPLITS and not args.unlock:
        print(f"{args.case_id} is in the {split} split, which is locked.\n"
              f"Looking at it now costs you the ability to use it later.\n"
              f"Pass --unlock if that is what you intend.")
        return 1

    criteria_set = load_criteria(record["procedure_id"])
    packet = ingest_case(args.case_id, CASES)

    print(f"{args.case_id}  split={split}  procedure={criteria_set.procedure_id} "
          f"v{criteria_set.version}")
    print(f"ingestion: {packet.processing_status.value}, "
          f"{len(packet.usable)}/{len(packet.documents)} documents usable, "
          f"~{packet.estimated_tokens} tokens (estimate)")
    print(f"manifest:  {packet.manifest_check.get('status')}")

    if packet.manifest_check.get("status") == "mismatch":
        print("  hashes disagree with the manifest; "
              f"{packet.manifest_check.get('changed')}")

    if packet.processing_status is ProcessingStatus.FAILED:
        print("\nPacket failed ingestion. No extraction will be attempted, and "
              "this is reported as an incomplete processing state rather than "
              "as a clinical result.")
        for doc in packet.failed:
            print(f"  {doc.filename}: {doc.outcome.value} — {doc.detail}")
        return 1

    prompt = build_extraction_prompt(criteria_set, packet)
    calls = 1 if args.config == "A" else len(criteria_set.criteria)
    print(f"\nconfiguration {args.config}: {calls} call(s), model {args.model}")
    print(f"prompt {prompt.prompt_version}: system {len(prompt.system)} chars, "
          f"criteria {len(prompt.criteria_block)}, record {len(prompt.record_block)}")

    if args.dry_run:
        print("\n--dry-run: nothing was sent.")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nANTHROPIC_API_KEY is not set.\n"
              "  cp .env.example .env    then put the key on the "
              "ANTHROPIC_API_KEY line.\n"
              ".env is gitignored and is never written into a run log.")
        return 1

    # UM_MAX_RETRIES counts retries; the first call is not a retry.
    attempts = int(os.environ.get("UM_MAX_RETRIES", MAX_ATTEMPTS - 1)) + 1
    timeout = float(os.environ.get("UM_REQUEST_TIMEOUT_SECONDS",
                                   DEFAULT_TIMEOUT_SECONDS))

    client = AnthropicClient()
    run = extract(criteria_set, packet, client,
                  configuration=args.config, model=args.model,
                  max_attempts=attempts, timeout=timeout)

    # Step 4 always runs and needs no model. Step 5 is a second call per
    # criterion carrying a claim, so it is separately skippable.
    verified = verify_run(run, packet, criteria_set,
                          None if args.no_support else client,
                          model=args.model, timeout=timeout,
                          max_attempts=attempts)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "runs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{stamp}_{args.case_id}_{args.config}.json"
    out_path.write_text(json.dumps({
        "case_id": args.case_id,
        "split": split,
        "parent_case_id": record.get("parent_case_id"),
        "criteria_set_version": criteria_set.version,
        "preflight": checks.as_dict(),
        "packet": packet.as_dict(),
        "settings": {"model": args.model, "configuration": args.config,
                     "max_attempts": attempts, "timeout_seconds": timeout},
        "extraction": run.as_dict(),
        "verification": verified.as_dict(),
    }, indent=2), encoding="utf-8")

    print(f"\nextraction: {run.processing_status.value}  "
          f"calls={run.calls}  in={run.input_tokens}  out={run.output_tokens}  "
          f"{run.seconds:.1f}s")
    rejections = run.contract_rejections
    if rejections:
        print(f"  contract rejections: {len(rejections)} "
              f"(reported apart from clinical errors)")

    valid = verified.citation_validity
    print(f"verification: {verified.verified_spans}/{verified.returned_spans} "
          f"quotes verified"
          f"{'' if valid is None else f' ({valid:.0%})'}"
          f", {sum(1 for r in verified.results if r.downgraded)} downgraded")

    print(f"\n{'criterion':10} {'status':14} {'was':10} {'ev':>3} {'ok':>3}  "
          f"{'support':12} reason codes")
    for r in verified.results:
        status = r.clinical_status.value if r.clinical_status else "—"
        was = (r.extracted_status.value
               if r.extracted_status and r.downgraded else "")
        codes = ", ".join(c.value for c in r.reason_codes)
        print(f"{r.criterion_id:10} {status:14} {was:10} "
              f"{len(r.evidence):>3} {len(r.verified_evidence):>3}  "
              f"{r.support_outcome:12} {codes}")
        for detail in (r.detail, r.downgrade_reason):
            if detail:
                print(f"           {detail}")

    print(f"\nrun log: {out_path.relative_to(PROJECT_ROOT)}")
    print("Clinical status and processing status are separate throughout. A "
          "status shown as — means no clinical result was produced, which is "
          "not the same as unresolved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
