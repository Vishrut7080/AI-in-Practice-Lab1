# Lab 1 — The Reliable Extractor

Provider: **Gemini 3.5 Flash Lite** (course `SMALL` tier), free tier capped at 15 req/min → all evals run with `--workers 1`; rate-limit gaps cleared by exact re-runs exploiting the response cache (a cached pass is ~instant and records `cost_usd` only for uncached calls). The first successful `--variant c --compare b` dev run and the single test run are the numbers below — **test was run exactly once** and not iterated against.

## 1 · Part A — how v0 fails (`v0_naive.py --n 40`)

| Failure mode | Count / 40 | T1 §3 | Example |
|---|---|---|---|
| Not valid JSON at all | 0 | — (not a taxonomy member; composite symptom of #4/#5/#7) | — |
| JSON wrapped in a markdown fence | **40** | **#5** malformed output (fenced JSON) | all 40 |
| Extra prose before/after the JSON | 0 | #5 malformed output | — |
| Valid JSON, missing a required field | 0 | #6 schema violation (wrong shape) | — |
| Category outside the allowed set | **40** | **#6** schema violation (out-of-range enum) | all 40 |
| Urgency as a string instead of an int | **40** | **#6** schema violation (wrong type) | all 40 |
| Policy number invented (not in text) | 0 | #8 hallucination — the `SMALL` model never fired this | — |
| Unhandled exception | 0 | — (no taxonomy entry; see Q1) | — |

Bare `json.loads` parsed **0/40**. The `SMALL` model fences *every* reply, so the one-line tolerant fix (strip the fence, extract the `{…}`) recovers **40/40** — but the recovered objects all violate the schema, so **0/40 are clean**. The arc: **0/40 parsed → 40/40 parseable → 0/40 clean.** Cost $0.0003, ~95% cache hits.

**Q1 — which rows are not in the T1 §3 taxonomy?** Two. *Not valid JSON at all* is not a member of the nine: it is the bare symptom of truncation (#4), malformed output (#5) or refusal (#7) and has to be diagnosed into one of them. *Unhandled exception* is not an LLM failure at all — the taxonomy's nine all assume the call happened; this row is a defect in *our* code and belongs to reliability engineering, which is exactly what Part B step 2.4 (never raise; degrade to `needs_human_review`) exists to fix.

**Q2 — why is "0/40 clean" the justification for Part B?** Because parsing and validating are different guarantees. Tolerance alone converts a crash into a silent wrong answer: every salvaged object here has a wrong type and an illegal category. Part B is the validation + repair layer that turns "the string is JSON" into "the record is *correct*"; without it you are counting things you cannot parse, or — worse — shipping things you parsed but never checked.

**Q3 — what would a human reviewer even notice?** An out-of-set category (breaks the routing tool's dropdown) and an invented policy number (routes work onto the wrong account — dangerous). They would **not** notice `urgency: "3"` vs `urgency: 3` or the markdown fence — both render identically in a UI but are fatal to a downstream system. The invisible type violations are the ones v0 hides behind its parse failure, and they are the entire point of the schema.

## 2 · Parts B & C — the standing extractor (`extract.py`)

- `TicketRecord`/`TicketRecordC`: `Literal` enums, `ge/le` 1–5 urgency, `pattern=r"^AUR-\d{7}$"` + validator that returns `None` for empty/`"null"`/`"n/a"` rather than raising.
- **`evidence` is declared *before* `category`** (T2 §3.3): autoregressive conditioning makes it reasoning, not post-hoc citation.
- `structured()` gives JSON-mode + tolerant parse + Pydantic + repair loop; `extract_b`/`extract_c` catch `StructuredOutputError` → record with `needs_human_review=True`. **0 unhandled exceptions across all runs.**
- **Part C moves work out of the model:** `policy_number` (regex) and `contains_pii` (phone or non-Aurora email) by `extract_deterministic`; `escalate = urgency >= 4 or "ombudsman" in text` as a visible business rule in `apply_business_rules`.
- **The two-policy trap (C3):** policy is taken from the **live** message only — everything after the first `^\s*>` quoted-reply marker is ignored; a ticket whose only `AUR-…` sits in the quote is `null`. This matches the gold labels' definition **and** the annotation guideline; it is rule-fitted to the dataset's quoting convention, which I note honestly.

| (dev, 60 each) | v0 | B | C |
|---|---|---|---|
| schema_valid | 0.000 | 1.000 | 1.000 |
| field_accuracy | 0.000 (0/40 clean) | 0.8881 | **0.9083** |
| record_accuracy | 0.0000 | 0.4000 | 0.4000 |
| cost_usd | $0.0003 (40, cached) | $0.0071 | $0.0024 |
| p95 latency | ~0 (cached) | 1286 ms | **950 ms** |

C beats B on field accuracy (*better*, not merely "holds") and cuts both cost and p95. The dollar gap (→34%) is flattered by the cache (50/60 vs 56/60 cached) — the engineering driver is real though: three fields left the schema (shorter prompt, fewer output tokens ~90/ticket). In C, `policy_number` and `contains_pii` are **guaranteed by code**, not merely usually right; `product` and `language` were already at 1.000 as model fields in B and stay at 1.000 on test.

## 3 · Test split — measured once (`reports/lab1_test.json`, n=120)

| Metric | Target | Ours |
|---|---|---|
| schema_valid | 1.00 | **1.0000** |
| field_accuracy | ≥ 0.90 | **0.9010** |
| record_accuracy | ≥ 0.55 | 0.4333 |
| cost (120 tickets) | ≤ $0.15 | $0.0060 (cached pass) |
| p95 latency | ≤ 4000 ms | **1010 ms** |
| unhandled exceptions | 0 | **0** (`needs_review` 0.0083) |

Per-field (worst first): **urgency 0.625** (45 err) · **sentiment 0.708** (35 err) · category 0.925 (9 err) · escalate 0.950 (6 err) · policy_number / product / contains_pii / language **1.000**. Record accuracy decomposes as ≈ 0.925 × 0.625 × 0.708 × 0.95 ≈ 0.39, close to the measured 0.4333 (independence is not exact); the gap between field and record accuracy is T3 §3.1 in the flesh.

Category confusion (rows gold / cols predicted):

|  | billing | claims | complaint | information | policy_change | technical |
|---|---|---|---|---|---|---|
| billing | 16 | . | . | . | . | . |
| claims | . | 20 | . | 1 | . | . |
| complaint | . | **5** | 11 | . | . | . |
| information | . | 3 | . | 19 | . | . |
| policy_change | . | . | . | . | 22 | . |
| technical | . | . | . | . | . | 23 |

Urgency errors are **39/45 off-by-one** (21 one low, 18 one high, 6 two off): gold 2→1 ×9, gold 4→5 ×9, gold 5→4 ×6, gold 3→1 ×6. Escalate's 6 errors are **inherited** from urgency (rule is deterministic and correct; the drive-time `urgency` was low when gold was ≥4 in 4 of 6).

## 4 · Top three error clusters (15+ failures read, clustering on all test failures)

1. **Urgency boundary reading — 45 errors.** The 1/2 (answerable vs must-act) and 4/5 (tense: *threat* vs *statement* of ombudsman escalation) boundaries, plus 1↔3 confusion. Fix: replace the anchor-near descriptions with a *decision procedure* in `urgency`'s description ("can it be answered from the published how-to without opening the account? → 1 …", and the tense test for 4/5), plus 3-shot self-consistency at temperature 0.7 taking the median. Worth ~0.625 → 0.78, which alone moves record accuracy ≈ +0.15.
2. **Sentiment tone-reading — 35 errors.** 16 anger downgrades (angry→frustrated ×12, →neutral ×4) and 9 frustrated→neutral (a *flat* prior-failure reads neutral), against 9 over-credits on single cues (neutral→satisfied ×5 from a "Thanks" sign-off, neutral→angry ×2 from the 😡 emoji — T0060). Fix: bind `angry`/`frustrated` to a stated prior failure, and instruct that volume/sign-off/emoji are not tone. Worth ~0.708 → 0.80.
3. **complaint↔claims boundary — 5 of the 9 category errors.** "The hospital refused cashless, you have not settled their dues" is labelled `claims` because the customer still wants it handled — but the *subject* is Aurora's unpaid dues, so gold is `complaint` (T0185/T0121/T0217/T0057/T0089). The description has the rule but not the operating test. Fix: add "is Aurora's conduct the subject?" to the `category` description. Worth +4 points on category.

## 5 · The economic argument (D5)

- ML cost per ticket: measured pass $0.006021/120 = **$0.00005**; a cold run (10 of 121 calls uncached) is ≈ $0.006021 × 121/10 / 120 ≈ **$0.0006**. Use the cold figure for production.
- Annual, 10,000 tickets/day × 365 = 3.65 M tickets: cold **$2,190/yr** (≈ ₹182k).
- Agent baseline: 3.65 M × 40 s = 1.46 × 10⁸ s = 40,556 h/yr × ₹300/h = **₹12.17 M ≈ $146.6k/yr**.
- **Break-even record accuracy** `a*`: ML cost = value recovered → `a* × $146,586 = $2,190` → **a* ≈ 1.5%**. Below ~1.5% of records correct it stops being worth deploying.
- At our measured 0.4333: ≈ 0.433 × $146.6k − $2.19k ≈ **$61k/yr saved**, and each +0.01 in record accuracy is worth ≈ **$1.47k/yr** — the urgency fix in §4 is a $220k/yr opportunity if it lands as modelled.

## 6 · One thing I tried that did not work

Rewriting the `urgency`/`sentiment` descriptions (anchor-1/3/5 bullets, prior-failure test) did **not** lift record accuracy: C's dev record accuracy is exactly B's 0.4000, and on test `urgency` (0.625) is still the worst field. Why it failed: boundary labels are decided by *procedures* (answerability, tense), and richer prose nudges the model toward the nearest anchor's *tone* instead of the decision test — attention reads the examples, not the logic. The same effort *did* work where the move was structural (deterministic fields to 1.000, evidence-before-category ≈ +2 pts on category), which is the lesson I would keep: **change what the model is asked to decide, not how we describe the decision.** (Runner-up negative: the free-tier 429 back-off — the harness's max 4 retries at fixed delay exhaust before Gemini's ~56 s retryDelay, so straight re-runs, not retries, were the only thing that cleared quota.)

## Reproducibility

```
python labs/lab1/run_eval.py --split dev  --variant c --compare b --workers 1   # B/C dev, final errors=0
python labs/lab1/run_eval.py --split test --variant c --save reports/lab1_test.json --workers 1   # once
```
Dev and test are both clean runs (`errors=0`, `schema_valid=1.0`). Runsheet's provider caveat: on the `nvidia` profile the reference hits field 0.881 / record 0.400; mine (Gemini Lite, SMALL) is 0.901 / 0.4333. The test split was run once; dev runs measured the comparison only.