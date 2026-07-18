"""'No result' has several causes with opposite responses.

The failure this workflow exists for is not a bad result -- it is the absence of
one, which no inbox displays and no queue holds.
"""

from datetime import datetime, timedelta

import pytest

from interstitium import scenarios
from interstitium.phi import scan
from interstitium.runtime import (
    Context,
    Disposition,
    Encounter,
    Knowledge,
    Signal,
    evaluate,
)
from interstitium.workflows import LabResultIntegrityWorkflow

NOW = datetime(2026, 7, 20, 15, 0)
WF = LabResultIntegrityWorkflow()


def ctx(facts=None, now=NOW, patient=None):
    encounter = Encounter(
        id="enc-1",
        patient=patient or scenarios.PATIENT,
        discharged_at=datetime(2026, 7, 18, 15, 10),
        pending_results=["urine culture"],
        empiric_therapy="ciprofloxacin",
    )
    signal = Signal("result_overdue", NOW, {"order": "urine culture", "overdue_by": "26h"})
    return Context(encounter, signal, Knowledge(facts or {}), now)


def test_unknown_cause_queries_the_lab_rather_than_assuming_a_delay():
    d = evaluate(WF, ctx())
    assert d.disposition is Disposition.GATHER_FACTS
    assert "laboratory" in d.action


def test_result_exists_in_lis_but_never_delivered_is_an_interface_failure():
    """The most dangerous case: the lab thinks it is done, the chart shows
    nothing pending, and the answer sits in a system nobody is looking at."""
    d = evaluate(WF, ctx({"specimen_status": "resulted", "result_available_in_lis": True}))
    assert d.escalates
    assert any("delivery failure" in r for r in d.reasons)
    assert any("never been reviewed" in r for r in d.reasons)


def test_specimen_never_reached_the_lab_requires_recollection():
    d = evaluate(WF, ctx({"specimen_status": "never_received", "result_available_in_lis": False}))
    assert d.escalates
    assert "recollection" in d.action
    assert any("no result will ever arrive" in r for r in d.reasons)


def test_rejected_specimen_is_not_the_same_as_a_pending_one():
    d = evaluate(WF, ctx({
        "specimen_status": "rejected",
        "result_available_in_lis": False,
        "rejection_reason": "insufficient volume",
    }))
    assert d.escalates
    assert any("insufficient volume" in r for r in d.reasons)


def test_assay_still_running_is_not_a_fault():
    d = evaluate(WF, ctx({"specimen_status": "in_progress", "result_available_in_lis": False}))
    assert d.disposition is Disposition.MONITOR


def test_unrecognised_lab_status_is_not_treated_as_benign():
    d = evaluate(WF, ctx({"specimen_status": "held_pending_review", "result_available_in_lis": False}))
    assert d.escalates


def test_monitoring_a_running_assay_still_cannot_continue_forever():
    d = evaluate(WF, ctx(now=NOW + WF.gather_window + timedelta(hours=1)))
    assert d.escalates


def test_an_unreachable_patient_does_not_block_a_lab_query():
    """Facts come from the laboratory here, so a missing phone number is
    irrelevant -- the runtime must not block on patient reachability."""
    from dataclasses import replace

    from interstitium.models import Contact

    unreachable = replace(
        scenarios.PATIENT, contact=Contact(phone="(415) 555-0148", verified_at=None)
    )
    d = evaluate(WF, ctx(patient=unreachable))
    assert d.disposition is Disposition.GATHER_FACTS


@pytest.mark.parametrize(
    "facts",
    [
        {"specimen_status": "never_received", "result_available_in_lis": False},
        {"specimen_status": "resulted", "result_available_in_lis": True},
    ],
)
def test_summaries_carry_no_identifiers(facts):
    assert scan(WF.escalation_summary(ctx(facts)), scenarios.PATIENT) == []
