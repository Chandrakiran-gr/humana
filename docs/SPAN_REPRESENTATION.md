# Canonical Span Representation

Decided at Task 2.1, before ingestion was written. Steps 4 and 6 both depend on
this and neither can be changed independently of it.

## What a span has to do

A citation that cannot resolve to a location is not verifiable, and
verifiability is the product. Four requirements, from Spec Sections 3, 4 and 10:

1. **Support exact string matching.** Step 4 verifies a returned quote by string
   match against a stable canonical representation of the source.
2. **Map back to the original.** Where normalization is applied, a mapping back
   to the original source is retained, and Step 10 requires clicking a citation
   to open the source *at the cited span*.
3. **Disambiguate repeated quotes.** The same sentence may appear twice in a
   packet, once as a copy-forward block. Spec Section 4 requires repeated quotes
   to be disambiguated by document identity and span.
4. **Never silently alter clinical wording or numbers.**

## The decision

**A span is a half-open character range `[start, end)` into the document's
canonical text, carried alongside the document identifier and the content hash
of the raw bytes.**

```
{"document_id": "doc_a3f19c22b410", "content_sha256": "…",
 "start": 1284, "end": 1319}
```

Canonical text is produced from the raw text by a normalization that touches
whitespace and Unicode form only, and an offset map from every canonical
position back to its raw position is retained.

## Why character offsets and not the alternatives

**Not line and column.** Line numbers are unstable under reflow, and text
extracted from a PDF has no reliable line structure to begin with: the same
paragraph may extract as one line or as twelve depending on the producer. A
citation whose location changes when the extractor changes is not a citation.

**Not byte offsets into the raw file.** Byte offsets are ambiguous under
multi-byte encodings and break the moment a document is re-saved in a different
encoding. They also cannot be compared meaningfully against a model's returned
string, which is characters.

**Not the quote string alone.** This is the tempting option because a quote
looks self-locating. It fails requirement 3 outright. TKA-005V contains an
examination block reproduced verbatim from an earlier note; MRI-005 carries a
copy-forward paragraph. A quote-only citation cannot say which occurrence it
means, and those are exactly the passages where the distinction matters.

**Character offsets** satisfy all four. They form a total order, so spans sort,
nest and overlap-test cheaply, which Step 6 needs when assembling several spans
per criterion. Substring search returns them directly. And `(document_id, start)`
is unique within a document, which gives requirement 3 for free.

## The normalization, and its limits

Canonical text is derived by exactly three operations, in order:

1. **Unicode NFC.** So that a precomposed and a decomposed accent compare equal.
2. **Line endings to `\n`.** CRLF and CR both become LF.
3. **Runs of whitespace collapsed to a single space, leading and trailing
   whitespace on the document stripped.**

Step 3 is the one that earns its place and the one that carries risk, so the
reasoning is set out here. Clinical documents are hard-wrapped. A phrase the
model returns as `no back pain` may sit in the source as `no back\npain`,
because the line broke between the words. Without whitespace collapsing, that
quote fails verification and a correct citation is rejected as unverifiable —
which under the output contract downgrades a sound conclusion to unresolved.
Collapsing whitespace makes the comparison insensitive to wrapping, which is a
property of how the document was rendered rather than of what it says.

**No character that is not whitespace is added, removed, or changed.** No
lowercasing, no punctuation stripping, no number reformatting, no abbreviation
expansion, no spelling correction. `4+/5` stays `4+/5`. `36.6` stays `36.6`.
`L4-5` stays `L4-5`. This matters because the corpus turns on exactly such
tokens, and because a normalization that touched them could change a clinical
meaning without anyone noticing.

**The offset map is retained per document.** For every canonical index there is
the raw index it came from, so a span can always be projected back for display
and for the click-through in Step 10. The map is built during normalization
rather than reconstructed later, because reconstructing it requires re-deriving
the normalization and would drift if either side changed.

## What this does not solve

- **A quote that spans two documents** has no representation and is rejected.
  That is intended: evidence is a list, so two spans in two documents is the
  correct encoding, not one span across a boundary.
- **A model returning a paraphrase rather than a quote** will not match, and
  should not. Step 4 treats a mismatch as *unverifiable*, not as fabrication;
  Spec Section 4 is explicit that the two are different and that differences can
  arise from extraction and whitespace. Whitespace is handled here. Extraction
  differences are not, and remain a real source of rejected-but-honest quotes.
- **Normalization is not reversible in general.** Collapsing `a\n\n  b` to `a b`
  loses which whitespace was there. The offset map recovers *position*, not the
  original whitespace, which is all the display path needs.
- **A document whose text cannot be extracted has no canonical text and
  therefore no spans.** It cannot be cited at all, which is why the ingestion
  outcome for it is a processing failure rather than an empty success.

---

## Case folding: considered and declined

Recorded 2026-09-10, after the first development run and after examining every
citation it rejected. Kept rather than changed, which is worth writing down as
clearly as a change would be.

**The evidence for relaxing.** Of 114 returned citations, three did not verify.
**Two of the three differ from the source by one letter's case.** The model
began a quote partway through a sentence and lowercased the pronoun so the
fragment read naturally: it returned `she reports the current flare has been
going on for approximately 5 weeks` where the note says `She reports...`.
Capitalise the first character and both resolve to exactly one span.

That is a correct citation of a correct fact, discarded for one character. And
the rejection cascades: Step 4 downgrades a determinate status that has lost
any of its cited support, so in principle a capital letter could turn a correct
MET into AMBIGUOUS. None of the three did — all three instances were already
AMBIGUOUS — but the mechanism is real.

**The evidence for keeping it.** The third rejection was not a case difference.
The source reads `Mrs Okonkwo-Bright has suffered with her right knee for a
considerable time and has now had 18 months of failed conservative care.` The
model returned `she has now had 18 months of failed conservative care.`,
substituting a pronoun for the clause that was there. It resolves nowhere with
or without capitalisation. That is a paraphrase presented as a quotation — a
true statement about the record, and not a citation — and it is exactly what
Step 4 exists to catch.

**The decision.** Normalization stays at three operations and the guarantee
stays absolute: no character that is not whitespace is added, removed, or
changed.

The reasoning is about what happens next rather than about these three cases.
The current guarantee is checkable in one sentence, and a verified span is
byte-identical to its source modulo whitespace. Case-insensitive matching
replaces that with a guarantee that holds "except for capitalisation", and the
next request is punctuation, then stemming, then near-match. Each step is
individually reasonable and the endpoint is a matcher that accepts a
paraphrase. The third rejection is what that endpoint costs.

**What was done instead.** Extraction prompt 1.2.0 forbids adjusting
capitalisation to fit a quote, and says why in the instruction rather than
merely prohibiting it. The defect is an instruction gap, not a matcher gap: the
prompt already said not to correct spelling or expand abbreviations and said
nothing about case, so the model filled the silence sensibly.

**This is a hypothesis, and it is falsifiable.** If citations still fail on
case after 1.2.0, the prompt is not the fix and the matcher question reopens
with evidence rather than argument. The figure to watch is unverifiable
citations attributable to case alone, which was 2 of 114 under 1.1.0.

### What 1.2.0 actually did

Measured 2026-09-10, one run of the development split under each version.
Recorded in full because the clause achieved its narrow aim and the run around
it got worse, and reporting only the first half would be a selective reading.

| | 1.1.0 | 1.2.0 |
|---|---|---|
| Unverifiable citations | 1 of 114 | 1 of 129 |
| Case-difference misses | 2 of 114 (earlier run) | **0** |
| Evidence recall | 83.3% (91 of 103) | **80.6% (83 of 103)** |
| Evidence precision | 80.5% (99 of 123) | **69.0% (89 of 129)** |
| Status agreement | 93.1% (81 of 87) | **89.5% (77 of 86)** |
| Critical errors | 3 | **5** |

**The narrow aim was met.** No citation failed on capitalisation. The
falsification condition recorded above — unverifiable citations attributable to
case alone — went from 2 to 0, so the matcher question does not reopen.

**Everything else moved the wrong way.** Recall fell 8 points, precision 11,
and critical errors rose from three to five.

**This is one run against one run and the attribution is not established.**
Output tokens across the whole split moved 0.98x, so the clause is not
producing materially more text. But the run-to-run variance measured on the
same day is large — MRI-007 generated 11,288 tokens on one run and 6,893 on
another from identical input — and a corpus of 87 instances cannot separate an
8-point move from that. The honest reading is that **1.2.0 fixed the thing it
was written for and the surrounding figures are not yet interpretable.**

What follows from that: the Baseline A figure used in the scored comparison
must come from the same version as Candidate B, and neither of these two runs
is that figure. Both are diagnostic.

