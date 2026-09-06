"""Unit tests for the Lab 1 extractor's deterministic parts. `make test`.

Model-free by design: tests the code we moved OUT of the model in Part C —
`extract_deterministic` (policy_number, contains_pii) and the `escalate`
business rule. No API key, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from labs.lab1.extract import apply_business_rules, extract_deterministic


# --- policy_number comes from the LIVE message only -----------------------
def test_policy_number_from_live_message_not_quoted_reply():
    ticket = (
        "Please process my claim on AUR-1234567.\n"
        "> On 2 Mar you wrote: AUR-9999999 has no active claim.\n"
        "> This is not the number you are looking for."
    )
    assert extract_deterministic(ticket)["policy_number"] == "AUR-1234567"


def test_policy_only_in_quoted_reply_is_null():
    ticket = "> AUR-9999999 has been closed.\nThanks."
    assert extract_deterministic(ticket)["policy_number"] is None


def test_policy_number_when_no_quote_marker():
    ticket = "On 2 Mar AUR-8888888: please refund the premium."
    assert extract_deterministic(ticket)["policy_number"] == "AUR-8888888"


def test_no_policy_number_is_null():
    assert extract_deterministic("How do I submit a claim?")["policy_number"] is None


# --- contains_pii ----------------------------------------------------------
def test_phone_number_counts_as_pii():
    assert extract_deterministic("Call me on 9851952415 please")["contains_pii"] is True


def test_aurora_owned_email_does_not_count():
    ticket = "Mail support@aurorahealth.example for help."
    assert extract_deterministic(ticket)["contains_pii"] is False


def test_foreign_email_counts_as_pii():
    ticket = "Reach me at zoya.rao47@example.com anytime."
    assert extract_deterministic(ticket)["contains_pii"] is True


def test_personal_name_alone_does_not_count():
    assert extract_deterministic("Regards, Zoya Rao")["contains_pii"] is False


# --- escalate is a business rule in code -----------------------------------
def test_urgency_four_escalates():
    rec = apply_business_rules({"urgency": 4}, "still waiting")
    assert rec["escalate"] is True


def test_urgency_three_does_not_escalate():
    rec = apply_business_rules({"urgency": 3}, "still waiting")
    assert rec["escalate"] is False


def test_ombudsman_keyword_escalates_any_urgency():
    rec = apply_business_rules({"urgency": 2}, "I am going to the ombudsman")
    assert rec["escalate"] is True


def test_escalate_ignores_case():
    rec = apply_business_rules({"urgency": 1}, "The Ombudsman will hear about this")
    assert rec["escalate"] is True