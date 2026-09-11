# Run artifacts

Every number reported in `README.md` and `evals/results/` comes from a file in
this directory. They are committed so the results can be checked by reading
rather than by re-running, which would cost money, need a key, and — because
the model is not deterministic — not reproduce exactly anyway.

Most runs made during the build are **not** here. What is kept is the run that
backs a reported number, plus three artifacts the test suite depends on.
Everything else was intermediate or superseded.

**Runs before the extended-thinking fix of 2026-09-10 are excluded.** Thinking
was on by default and was the single cause of the token, latency and
truncation variance recorded in `docs/DATA_CARD.md`; anything measured before
it is invalid and is not kept where it could be mistaken for a result. The
three single-case replay artifacts below are the one exception, and they are
used only for a check that the fix does not affect.

## What backs what

| Result | Artifacts |
|---|---|
| Development, Baseline A | `20260910T213858Z_eval_batch7_A.json`, `20260910T213538Z_eval_batch8_A.json` |
| Development, Candidate B | `20260910T222444Z_eval_batch7_B.json`, `20260910T221928Z_eval_batch8_B.json` |
| Held-out, Baseline A | `20260910T223110Z_eval_batch5_A.json`, `20260910T223755Z_eval_batch4_A.json` |
| Held-out, Candidate B | `20260910T224634Z_eval_batch5_B.json`, `20260910T225318Z_eval_batch4_B.json` |
| Transfer, Baseline A | `20260910T230714Z_eval_transfer_A.json` |
| Claim-verification set | `20260910T233307Z_claimset.json` |
| Injection challenge, run 1 | `20260911T001324Z_injection_challenge.json`, `20260911T001751Z_injection_challenge_unfenced.json` |
| Injection challenge, run 2 | `20260911T002810Z_injection_challenge.json`, `20260911T002922Z_injection_challenge_unfenced.json` |

Development and held-out are split across two files each because the eval
harness was run in batches to survive interruption. Batch 7 and 8 together are
the 15 development cases; batch 4 and 5 together are the 9 held-out cases.

The injection challenge was run twice. The first run failed to evaluate one of
its four pre-registered criteria — the check for whether an injected document
was cited compared against a dictionary key that does not exist, so it never
fired. The second run measures it. **Both are kept.** The first run's three
working criteria stand and the second completes the fourth; discarding it
would hide that the first was incomplete.

## Artifacts the tests depend on

| File | Used by |
|---|---|
| `20260910T205411Z_eval_batch8_A.json` | `tests/test_faults.py` replays a real truncation out of this file. The fault injection control reproduces an observed failure rather than an invented one, and this is the observation. |
| `20260910T034251Z_MRI-005_A.json` | `tests/test_verify.py` replays recorded quotes against the packets to confirm every span still resolves. It globs `*<case>*.json`, which the batch artifacts do not match. |
| `20260910T153901Z_TKA-004_A.json` | as above |
| `20260910T154202Z_MRI-004_A.json` | as above |

Without these the suite does not fail loudly on a fresh clone — it *skips*,
which is lost coverage wearing the costume of a pass. That was found by
building a clone from the tracked files and running it, not by reading
`.gitignore`.

## What is in one

An eval artifact holds, per case and per criterion: the extracted evidence,
the quote-verification outcome for each span with its character offsets, the
support-verification outcome, the final clinical status and processing state,
and the comparison against the reference label. It also carries every attempt
made, including the ones that were rejected, so a retry or a parse failure is
visible rather than smoothed away.

`runs/live/` is not tracked. It is where the interface writes a live
demonstration run, deliberately outside the path the evaluation harness and
the recorded-run picker read, so a demonstration can never be mistaken for a
scored result.

## No keys

Spec Section 11 holds API keys outside source files and saved artifacts.
`um_evidence/extract.py` scrubs attempt text and error strings before they are
written, and `um_evidence/live.py` scrubs the serialised payload again before
it touches disk. `tests/test_live.py` asserts the artifact carries no key.
