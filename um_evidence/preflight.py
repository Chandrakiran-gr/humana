"""Startup checks that run before any model call.

Written because a version already drifted. `.env.example` once declared a
prompt version that disagreed with the code, and nothing would have caught it,
because nothing read the value: every run would simply have been filed under a
prompt that did not exist. A run log that is confidently wrong about what
produced it is worse than one that says nothing, because the error is only
discoverable by re-deriving the thing the log was supposed to record.

The rule this enforces is that a fact has one source. Where a fact is declared
in more than one place, the checks here require the declarations to agree, and
fail loudly where they do not. Where a fact belongs to an artifact — the
criteria version to criteria_sets.json, the prompt version to prompts.py — it
must not also be settable from the environment, because an environment value
can silently outlive the thing it describes.

Nothing here is a convention. Each check fails a run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .criteria import DEFAULT_CRITERIA_PATH
from .prompts import PROMPT_VERSION

DEFAULT_LABELS_PATH = Path(__file__).resolve().parents[1] / "corpus" / "labels.json"

# Facts that belong to an artifact and must never come from the environment.
# Their presence means a second source has been reintroduced, so the check is
# for presence rather than for value: a correct value today drifts tomorrow.
BANNED_ENV_KEYS = ("UM_PROMPT_VERSION", "UM_CRITERIA_SET_VERSION")


class PreflightError(RuntimeError):
    """Configuration disagrees with what is on disk. The run does not start."""


@dataclass(frozen=True)
class Preflight:
    model: str
    prompt_version: str
    criteria_set_version: str
    findings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.findings

    def raise_if_failed(self) -> "Preflight":
        if self.findings:
            raise PreflightError(
                "Preflight failed. No model call was made.\n" +
                "\n".join(f"  - {f}" for f in self.findings))
        return self

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "criteria_set_version": self.criteria_set_version,
        }


def declared_criteria_version(path: Path | str = DEFAULT_CRITERIA_PATH) -> str:
    """The one criteria version, or an error naming every disagreement.

    The file declares it in `_meta` and again in each criteria set. They are
    required to agree, so that "the criteria version" names one thing.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    declared: dict[str, str] = {}
    meta_version = payload.get("_meta", {}).get("criteria_set_version")
    if meta_version:
        declared["_meta"] = meta_version
    for raw_set in payload.get("criteria_sets", []):
        declared[raw_set["procedure_id"]] = raw_set.get("criteria_set_version")

    if not declared:
        raise PreflightError(f"{path} declares no criteria_set_version")
    distinct = set(declared.values())
    if len(distinct) != 1:
        listed = ", ".join(f"{k}={v}" for k, v in sorted(declared.items()))
        raise PreflightError(
            f"criteria_sets.json declares more than one version: {listed}")
    return distinct.pop()


def _label_version_findings(labels_path: Path, criteria_version: str) -> list[str]:
    if not Path(labels_path).exists():
        return [f"labels not found at {labels_path}"]
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    stale = sorted({
        case["criteria_set_version"] for case in labels.get("cases", [])
        if case.get("criteria_set_version") != criteria_version})
    if stale:
        return [f"corpus/labels.json has cases labelled against criteria "
                f"version(s) {stale}, but criteria_sets.json declares "
                f"{criteria_version}. The labels describe criteria that are "
                f"no longer the ones being loaded."]
    return []


def preflight(model: str | None = None,
              criteria_path: Path | str = DEFAULT_CRITERIA_PATH,
              labels_path: Path | str = DEFAULT_LABELS_PATH,
              env: dict | None = None,
              allow_model_override: bool = False) -> Preflight:
    """Check configuration against the artifacts. Never makes a call.

    Returns a Preflight carrying the resolved values and any findings. Call
    `raise_if_failed()` to turn findings into a stopped run.
    """
    from .extract import DEFAULT_MODEL

    env = os.environ if env is None else env
    findings: list[str] = []

    for key in BANNED_ENV_KEYS:
        if env.get(key):
            findings.append(
                f"{key} is set in the environment. This value belongs to the "
                f"artifact that produces it, not to configuration, and a second "
                f"source drifts. Remove it; the version is read from disk.")

    try:
        criteria_version = declared_criteria_version(criteria_path)
    except PreflightError as exc:
        findings.append(str(exc))
        criteria_version = ""

    if criteria_version:
        findings += _label_version_findings(Path(labels_path), criteria_version)

    resolved_model = (model or env.get("UM_MODEL") or "").strip()
    if not resolved_model:
        findings.append("no model configured: set UM_MODEL in .env")
    elif resolved_model != DEFAULT_MODEL and not allow_model_override:
        findings.append(
            f"configured model {resolved_model!r} disagrees with the code "
            f"default {DEFAULT_MODEL!r}. Spec Section 11 requires one model "
            f"version throughout, for evaluation and demonstration alike, so a "
            f"disagreement here would make runs incomparable. Make them agree, "
            f"or pass an explicit override if that is what you intend.")

    if not PROMPT_VERSION.strip():
        findings.append("prompts.PROMPT_VERSION is empty")

    return Preflight(model=resolved_model, prompt_version=PROMPT_VERSION,
                     criteria_set_version=criteria_version,
                     findings=tuple(findings))
