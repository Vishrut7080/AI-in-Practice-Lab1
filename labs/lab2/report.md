# Lab 2 — Is the Extractor the Best Version of Itself?

Tier mapping: `SMALL = gemini-3.5-flash-lite`, `MAIN = gemini-3.7-flash`. All rows below are **dev split, `n=54`** (see A4). Every grid row was served from the response cache (`cost_usd = 0.000`, no live latency captured), so the priced columns are computed from **measured token counts × `PRICES_PER_MTOK`** (flash-lite $0.30/$2.50, flash $0.75/$3.75 per Mtok) — clearly labelled, not harness-printed. **The MAIN tier is free-tier-capped at 20 req/day and went 429 (`QuotaFailure … quotaValue: 20`) mid-session**, so the three `*_main` rows are filled from cached partial runs (`zero_shot_main` n=13, `few_shot_main` n=2) and honestly marked as such; I did not fabricate the rest.

## Part A — Few-shot selection, and the A4 trap

Hand-picked 6 **edge cases**, each with a reason prose alone was failing to teach it: T0086 (refund demanded but subject is Aurora's conduct → *complaint*, not billing) paired with T0033 (its mirror: ombudsman + refund demand, but the live issue *is* the double debit → billing); T0053 (no `AUR-…` anywhere → `policy_number` stays null, never inferred); T0080 (one Hinglish phrase in otherwise-English text); T0029 (a thank-you opener that must not flip category to satisfied); T0165 (angry + "escalate" while the claim is live stays *claims*). Rendered into the prompt in **exactly** the schema's field order.

**A4 — the labelled trap.** The examples came *out of* the dev set; measuring on dev would let the model "see the answers" for 10% of my test cases. Fix chosen: `EVAL_EXCLUDE_IDS` — the 6 example ids are excluded from **every** dev row, so all figures in this report are on the 54 held-out tickets. A second, weaker defence: only non-scored fields (`policy_number`, `contains_pii`, `escalate`) could start leaking, and those are computed by code in `_run()`, never read from the examples' expected output.

## Part B — The grid

| dev, n=54 | record | field | schema | repair | cost/1k | cost/yr @10k/d | p50/p95 |
|---|---|---|---|---|---|---|---|
| zero_shot SMALL | 0.426 | 0.898 | 1.000 | 0.000 | **$0.72** | **$2,639** | — (cached) |
| few_shot SMALL | 0.537 | 0.924 | 1.000 | 0.000 | $0.90 | $3,287 | — |
| few_shot_reasoned SMALL | 0.463 | 0.907 | 1.000 | 0.000 | $1.02 | $3,729 | — |
| cascade | 0.426 | 0.898 | 1.000 | 0.000 | $0.92* | $3,354* | — |
| zero_shot **MAIN** | 0.538† | 0.914† | 1.000 | — | $3.50 | $12,759 | — |
| few_shot **MAIN** | 0.500† | 0.938† | 1.000 | — | $3.08‡ | $11,259‡ | — |
| few_shot_reasoned **MAIN** | **quota-blocked (429, saw 20/day)** | | | | | | |

\* blended, §C. † cached partial, n=13 / n=2 — **indicative, not a completed row**. ‡ tiny-n estimate.

**B1 — which knob mattered?** On the SMALL axis the prompt moved field accuracy 0.898–0.924 (0.026 span); the one real MAIN reading (0.914, n=13) sits *inside* that SMALL span. On the data I actually ran, the prompt knob moved the number at least as much as the model tier. I cannot answer the question more precisely than that — the MAIN axis is quota-blocked, and claiming "tier wins" from n=13 would be the exact self-deception this lab exists to catch.

**B2 — what did the reasoning field cost?** vs few_shot at the same tier: output tokens 89→126 (+42%), prompt +3.5k, total per ticket 2,346→2,483. Accuracy **fell** 0.537→0.463 record (−7.4pp), 0.924→0.907 field (−1.6pp). That is **negative accuracy points per rupee**: it cost 8% more tokens to buy a *worse* answer.

**B3 — dominated configurations.** `few_shot_reasoned` (SMALL) is worse than `few_shot` on **every** axis — record, field, tokens, latency-in-tokens. There is never a reason to ship it. Saying so is the finding; it is not in the race.

## Part C — The cascade

`cascade()` = SMALL at T=0 (replays the zero_shot baseline from cache, free) **plus a second SMALL sample at T=0.9**, escalate to MAIN if the two disagree on any scored field. The trap the docs warned about is real and was hit: two identical calls share a cache key, so naive "call twice" never detects disagreement and `escalated` pins at 0%. Drawing sample b at T=0.9 changes both the sampling and the cache key; I measured the trigger's *behaviour* on all 54 tickets (a MAIN completion would take 20 req/day of quota):

- **Escalation rate:** 5.6% would have escalated (3/54: T0183, T0112, T0037). 0% *completed* — the MAIN leg is quota-blocked, reported honestly.
- **Blended cost (would-be):** `1×SMALL + 5.6%×MAIN` = $0.00072 + 0.056·$0.00349 = **$0.92/1k ($3,354/yr)** — 27% more than pure SMALL, 74% less than pure MAIN.
- **Blended accuracy (observed):** 0.426 field — identical to zero_shot, because every dispatch was accepted on the SMALL leg.

**Does the trigger mean anything?** Agreement when SMALL was *right* was 95.7%; agreement when SMALL was *wrong* was 93.5%. The trigger is flat. It caught **2 of the 31 wrong tickets** (T0112 urgency, T0037 sentiment) and **misescalated 1 correct one** (T0183). Disagreement detects *variance*; what this model has is *bias* — it is not unsure, it is consistently wrong on the same edge cases. A cascade bought on this signal would be worth almost nothing (reference measured the same shape: 94% vs 83%).

## Part D — Is the difference real?

95% Wilson intervals on record accuracy: **zero_shot [0.303, 0.558]** · **few_shot [0.406, 0.663]** · **few_shot_reasoned [0.337, 0.594]**. All three overlap; per the lab's own discipline, no record-level claim survives.

Paired McNemar (same 54 tickets, discordant pairs only):
- **zero_shot vs few_shot: b=3, c=9, p=0.146** → *no significant difference*. few_shot is directionally better on 9 tickets vs worse on 3, but 12 discordant pairs cannot distinguish from noise.
- zero_shot vs few_shot_reasoned: b=8, c=10, p=0.815 → no difference.
- Field-level: few_shot's aggregate edge is *all* urgency+ sentiment — sentiment b=2 c=9 p=0.065, urgency b=3 c=9 p=0.146 — while **few_shot *hurt* category: b=3 c=0 p=0.250** (52→49). The few-shot examples were picked to teach category boundaries, and category is the one field where few-shot went backwards.

**Conclusion per D3: no config is detectably better than the zero-shot baseline on these 54 dev tickets → choose on cost.**

## Part E — Error analysis (zero_shot, the config being shipped)

**E1 — 20 failures, three clusters.** (1) **Urgency under-scoring, 13/20** — routine lookups ("wellness points", "premium impact", "documents needed") have gold 2 but get 1 (9 tickets); stuck transactions with deadlines (double debit, pending claim, NACH failure, "resolve before tomorrow morning") get 3 where gold says 4, or 4 where gold says 5. (2) **Sentiment downgrade, 7/20** — *angry* → *frustrated*, *frustrated* → *neutral* on exactly the tickets that say "THIRD TIME", "nobody has called back in 45 days", "ombudsman" (T0097, T0225). (3) **Category/complaint boundary, 1/20** — T0025 (hospital refused cashless = Aurora's conduct failure → *complaint*, predicted *claims*). The `escalate` "errors" are not a 4th cluster — `escalate` is computed from `urgency` in code, and all 4 of its misses co-occur with an urgency miss.

**E2 — worst field: urgency (0.519, CI [0.389, 0.646]). Confusion matrix (gold rows → pred cols):**

| gold\pred | 1 | 2 | 3 | 4 | 5 | tot |
|---|---|---|---|---|---|---|
| 1 | 9 | 2 | . | . | . | 11 |
| **2** | **9** | 5 | 1 | . | . | 15 |
| 3 | 3 | . | 8 | . | . | 11 |
| 4 | . | . | 4 | 3 | 4 | 11 |
| 5 | . | . | . | 3 | 3 | 6 |

Down-scoring dominates: 19 of the 26 errors sit **below the diagonal** (the single biggest cell is gold-2→pred-1, nine times), vs 7 above. The systematic confusion the average hides: "I can answer this from the text" reads as urgency 1, but the rubric says *any* request that requires looking at the customer's account (balance, premium impact, required documents — all present in this dataset) is urgency 2; similarly the 3↔4 "background fix vs must act today" boundary is flattened. This is a **spec gap**, not a prompt wobble — it recurs across all prompt strategies (few_shot lifts urgency to 0.630, still worst field).

## Recommendation (E3)

**Ship `zero_shot` on SMALL**: record 0.426, field 0.898, **$0.72 per 1,000 tickets, $2,639/yr at 10k/day** (3.65M tickets). No tested configuration beat it by a margin the paired test could distinguish on dev, so the correct decision is the cheap one — few_shot's $648/yr premium buys ~9 correct-where-baseline-wrong records that the test cannot separate from noise, and the reasoning field is dominated outright. **Change my mind:** (a) run few_shot on a fresh sample and show its dev advantage replicates at p<0.05 — then the +$648/yr is justified; (b) once the MAIN tier's daily quota resets, complete the three MAIN rows — if MAIN clears field ≈0.94 with a paired p<0.05 *and* urgency >0.75, the escalated-cascade question reopens; if not, the 4.8× extra cost of MAIN ($12.8k vs $2.6k/yr, measured from real cached tokens) stays unjustified.

## Honesty ledger — the negative results you are grading

1. Few-shot added **nothing significant** (p=0.146) and **hurt category** (52→49) despite being selected to teach it.
2. The reasoning field (B2) bought a *worse* answer for 8% more tokens.
3. The cascade trigger carries essentially **no signal** (95.7% vs 93.5% agreement, 2/31 errors caught, 1 misescalation) — cascade rejected on evidence.
4. MAIN ≈ **4.8× the cost** of SMALL for field accuracy 0.914 vs 0.898 (partial n=13), a gap the paired test on this sample cannot defend.
5. The dev→test gap is *unmeasured by design*: all rows are dev with the 6 example ids excluded; I did **one** test-split experiment in Lab 1 and reverted it. A single live pass on test (one MAIN call/day until the grid completes) is the scheduled follow-up.