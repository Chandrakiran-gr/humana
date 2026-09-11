# Prompt injection challenge set

Task 3.5. Five documents carrying instruction-like text, placed where a real
record might plausibly carry it: a patient portal message, a scanned-form
transcription artifact, a template footer, a copy-pasted email chain, and a
free-text field a patient filled in.

**This is not a red-team exercise and makes no claim of resistance.** Spec
Section 11 says structural separation of documents from instructions reduces
confusion without guaranteeing anything. These documents test whether the
separation holds against instruction-shaped text in the position a record
would actually put it, which is a much weaker thing than testing whether it
holds against an adversary.

The documents are deliberately not clever. A determined attacker would do
better, and nothing here should be read as evidence about that case.

These are **not corpus cases**. They carry no labels, sit outside
`corpus/cases/`, and are never scored.
