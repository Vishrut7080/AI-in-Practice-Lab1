#!/usr/bin/env python3
"""Lab 2 — the configurations under test.

Each variant is a callable `str -> dict`. `grid.py` runs them all through the
same harness, so the only thing that differs between rows of your table is the
thing you intended to differ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from labs.lab1.extract import (  # noqa: E402
    CATEGORIES,SYSTEM_PROMPT, TicketRecord, apply_business_rules, extract_deterministic,
)
from aip.llm import StructuredOutputError, structured  # noqa: E402

FEW_SHOT_IDS: list[str] = [
    "T0086",  # teaches: refund is demanded, but the SUBJECT is Aurora's
              # mis-selling conduct -> complaint, not billing
    "T0033",  # teaches: mirror image -- anger + ombudsman threat + refund
              # demand, but the live issue IS the double debit -> billing
              # (paired with T0086, this is the actual boundary contrast)
    "T0053",  # teaches: rich context but no AUR-XXXXXXX string anywhere ->
              # policy_number stays null, not inferred from "my policy"
    "T0080",  # teaches: hi-en from a single transliterated phrase dropped
              # into otherwise-English text, plus ignoring the ticket-header
              # boilerplate format
    "T0029",  # teaches: a thank-you opener doesn't make the whole ticket
              # 'satisfied'-flavored in category, and doesn't suppress a
              # real question underneath it
    "T0165",  # or T0037: teaches angry + emergency + "escalate" does NOT
              # flip category to complaint while the claim itself is still
              # live and the customer wants it handled -> stays 'claims'
]

EVAL_EXCLUDE_IDS = frozenset(FEW_SHOT_IDS)

def _run(ticket: str, schema, tier:str, temperature: float=None,
         extra_prompt:str="")->dict:
    """Call the model, then layer in the deterministic + business-rule fields.
 
    Every variant funnels through here so that policy_number / contains_pii /
    escalate are computed identically across the grid -- the only thing that
    should vary between rows is the prompting strategy (schema, few-shot
    block, model tier), not the extraction mechanics.
    """
    system = SYSTEM_PROMPT + ("\n\n" + extra_prompt if extra_prompt else "")
    kwargs = {"model": tier}
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        rec = structured(ticket, schema=schema, system=system, **kwargs)
        fields = rec.model_dump()
    except StructuredOutputError:
        fields = {
            "category": "information",
            "urgency": 1,
            "sentiment": "neutral",
            "product": "unknown",
            "language": "en",
            "evidence": "",
            "needs_human_review": True,
            "review_reason": "Could not produce a schema-valid record.",
        }
    fields.update(extract_deterministic(ticket))
    return apply_business_rules(fields, ticket)
    

def load_examples(ids: list[str]) -> list[dict]:
    rows = [json.loads(l) for l in
            (ROOT / "data/eval/extraction_dev.jsonl").open(encoding="utf-8")]
    by_id = {r["id"]: r for r in rows}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"unknown example ids: {missing}")
    return [by_id[i] for i in ids]

# Fields the MODEL is actually asked to produce -- excludes the two fields
# (policy_number, contains_pii) that _run() overwrites with
# extract_deterministic() output, and excludes needs_human_review /
# review_reason (set by code, never by the model, per TicketRecord's own
# docstring). Keeping these out of the few-shot examples avoids teaching the
# model a habit it isn't scored on and keeps the example format byte-identical
# to what the schema actually generates.
_MODEL_FIELDS = ("evidence", "category", "urgency", "sentiment",
                  "product", "language")

def few_shot_block(ids: list[str]) -> str:
    """Render the examples into the prompt.
 
    The example output format must be byte-identical to the format you are
    asking the model to produce -- same field set, same field order as the
    JSON Schema (evidence first, per B1a's chain-of-thought ordering).
    """
    examples = load_examples(ids)
    parts = ["Worked examples (follow this exact field order and format):"]
    for ex in examples:
        expected = ex["expected"]
        shot = {k: expected[k] for k in _MODEL_FIELDS if k in expected}
        parts.append(
            f"Ticket:\n{ex['input']}\n\nOutput:\n{json.dumps(shot, ensure_ascii=False)}"
        )
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# The variants
# ---------------------------------------------------------------------------
def zero_shot(ticket: str, tier: str = "SMALL") -> dict:
    """Lab 1 Part C, no examples. This is your baseline."""
    return _run(ticket, TicketRecord, tier)


def few_shot(ticket: str, tier: str = "SMALL") -> dict:
    """zero_shot + the few-shot block."""
    return _run(ticket, TicketRecord, tier, extra_prompt=few_shot_block(FEW_SHOT_IDS))


class TicketRecordReasoned(BaseModel):
    # """TODO B: add a `reasoning: str` field FIRST (T2 §3.3).

    # Pydantic keeps declaration order, and field order in the JSON Schema
    # influences generation order. Putting reasoning first makes it condition the
    # answer; putting it last makes it a post-hoc rationalisation. You want the
    # first. Measure the difference in output tokens.
    # """
    """TicketRecord with a `reasoning` field FIRST.
 
    Not built via subclassing TicketRecord: Pydantic v2 keeps inherited
    fields in their original position and appends new/overridden subclass
    fields after them, so `class TicketRecordReasoned(TicketRecord):
    reasoning: str = ...` would put `reasoning` LAST in the JSON Schema no
    matter where you write it in the class body -- exactly the "post-hoc
    rationalisation" ordering the docstring warns against. Declaring a fresh
    model with the field order written out explicitly is the only reliable
    way to control generation order.
    """
 
    reasoning: str = Field(
        description="Brief step-by-step reasoning that leads to the fields "
        "below. Write this FIRST -- decide the fields FROM the reasoning, "
        "not the other way around."
    )
    evidence: str = Field(
        max_length=200,
        description="the span of the ticket that determined the category, "
        "quoted verbatim",
    )
    category: CATEGORIES = Field(
        description=TicketRecord.model_fields["category"].description
    )
    urgency: int = Field(
        ge=1, le=5,
        description=TicketRecord.model_fields["urgency"].description,
    )
    sentiment: Literal["angry", "frustrated", "neutral", "satisfied"] = Field(
        description=TicketRecord.model_fields["sentiment"].description
    )
    product: Literal["bronze", "silver", "gold", "platinum", "unknown"] = Field(
        description=TicketRecord.model_fields["product"].description
    )
    language: Literal["en", "hi-en"] = Field(
        description=TicketRecord.model_fields["language"].description
    )
 
    needs_human_review: bool = False
    review_reason: str = ""
 
 
_REASONED_MODEL_FIELDS = ("reasoning",) + _MODEL_FIELDS

def _reasoned_few_shot_block(ids: list[str]) -> str:
    """Same as few_shot_block, but the worked examples need a `reasoning`
    field too. We don't have gold reasoning strings in the dev set, so we
    synthesize a short one from the gold fields themselves -- terse, but
    enough to show the model the field, and its position, at a glance.
    """
    examples = load_examples(ids)
    parts = ["Worked examples (follow this exact field order and format):"]
    for ex in examples:
        expected = ex["expected"]
        reasoning = (
            f"The evidence text points to a {expected['category']} issue; "
            f"tone reads as {expected['sentiment']}; the situation itself "
            f"(not the tone) puts urgency at {expected['urgency']}."
        )
        shot = {"reasoning": reasoning}
        shot.update({k: expected[k] for k in _MODEL_FIELDS if k in expected})
        parts.append(
            f"Ticket:\n{ex['input']}\n\nOutput:\n{json.dumps(shot, ensure_ascii=False)}"
        )
    return "\n\n---\n\n".join(parts)


def few_shot_reasoned(ticket: str, tier: str = "SMALL") -> dict:
    """few_shot with TicketRecordReasoned."""
    return _run(ticket, TicketRecordReasoned, tier,
                extra_prompt=_reasoned_few_shot_block(FEW_SHOT_IDS))


def cascade(ticket: str) -> dict:
    # """TODO C: SMALL first; escalate to MAIN on a trigger you choose.

    # Triggers, roughly in ascending order of how well they work:
    #   - validation failed                      (free, weak: misses confident errors)
    #   - evidence field empty or very short     (free, surprisingly decent)
    #   - urgency >= 4                           (free, but it is not a confidence signal)
    #   - two SMALL samples at T=0.7 disagree    (2x small cost, much the best)

    # Record which path each ticket took -- set rec['_path'] = 'small' | 'large'
    # so grid.py can report the escalation rate.
    # """
    """SMALL first; escalate to MAIN when two SMALL samples disagree.

    Trigger chosen as the strongest the docstring lists: two SMALL samples
    compared for agreement. The trap this avoids: two identical calls at the
    same temperature are byte-identical (temperature 0) or, worse, the *same
    cache key* even at temperature > 0 -- so the response cache serves the
    second sample from the first, disagreement is never detected, and the
    escalation rate silently pins at 0%. The fix is to draw the two samples
    under *different* cache keys / sampling: the first at the deterministic
    default (T=0, which also replays the zero_shot baseline from cache for
    free) and the second at T=0.9, which is a genuinely fresh stochastic draw.
    Records which path each ticket took in `_path` so grid.py can report the
    escalation rate; the second sample is stashed in `_sample_b` so the
    agreement-when-right vs agreement-when-wrong analysis is possible
    post-hoc.
    """
    a = _run(ticket, TicketRecord, "SMALL")
    b = _run(ticket, TicketRecord, "SMALL", temperature=0.9)

    disagree_fields = ("category", "urgency", "sentiment", "product", "language")
    disagreement = any(a.get(f) != b.get(f) for f in disagree_fields)

    if not disagreement:
        a["_path"] = "small"
        a["_sample_b"] = b
        return a

    result = _run(ticket, TicketRecord, "MAIN")
    result["_path"] = "large"
    result["_sample_b"] = b
    return result


VARIANTS = {
    "zero_shot": lambda t: zero_shot(t, "SMALL"),
    "zero_shot_main": lambda t: zero_shot(t, "MAIN"),
    "few_shot": lambda t: few_shot(t, "SMALL"),
    "few_shot_main": lambda t: few_shot(t, "MAIN"),
    "few_shot_reasoned": lambda t: few_shot_reasoned(t, "SMALL"),
    "few_shot_reasoned_main": lambda t: few_shot_reasoned(t, "MAIN"),
    "cascade": cascade,
}

