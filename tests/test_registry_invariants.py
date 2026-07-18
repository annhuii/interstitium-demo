"""Safety properties that hold for every workflow, present and future.

These tests are parametrised over `REGISTRY`, so a sixth workflow is covered the
moment it is registered. That is the whole argument for the runtime: the
invariant is enforced in one place and tested in one place, rather than
reimplemented per workflow and verified by hope.
"""

import itertools
from datetime import datetime, timedelta

import pytest

from interstitium import scenarios
from interstitium.models import Contact, Patient
from interstitium.phi import scan
from interstitium.runtime import (
    ALWAYS_PERMITTED,
    AUTONOMOUS,
    Context,
    Encounter,
    Knowledge,
    Signal,
    evaluate,
)
from interstitium.workflows import REGISTRY

NOW = datetime(2026, 7, 20, 15, 0)

IDS = [w.category for w in REGISTRY]


def encounter(**kw):
    base = dict(
        id="enc-1",
        patient=scenarios.PATIENT,
        discharged_at=datetime(2026, 7, 18, 15, 10),
        disposition="ama",
        problems=["acute myocardial infarction"],
        pending_results=["urine culture"],
        empiric_therapy="ciprofloxacin",
    )
    base.update(kw)
    return Encounter(**base)


def context_for(workflow, knowledge=None, **enc_kw):
    """A signal this workflow accepts, so `decide` is actually exercised."""
    payloads = {
        "pending_culture_empiric_therapy": ("culture_resulted", {"culture": scenarios.CULTURE}),
        "high_risk_ama": ("discharge", {}),
        "radiology_report_changed": ("report_amended", {}),
        "post_discharge_symptom_check": ("symptom_check_due", {"day": 3}),
        "discharge_open_loop_screen": ("discharge", {}),
    }
    kind, payload = payloads[workflow.category]
    return Context(
        encounter=encounter(**enc_kw),
        signal=Signal(kind, NOW, payload),
        knowledge=knowledge or Knowledge(),
        now=NOW,
    )


# ---------------------------------------------------------------- the invariant


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_no_workflow_acts_autonomously_while_facts_are_unknown(workflow):
    """The property the whole runtime exists to guarantee."""
    decision = evaluate(workflow, context_for(workflow))
    assert decision.disposition not in AUTONOMOUS, (
        "{} acted with nothing established".format(workflow.category)
    )


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_dropping_any_single_fact_prevents_autonomous_action(workflow):
    """Complete-minus-one must never be treated as complete."""
    required = workflow.required_facts()
    if not required:
        pytest.skip("no required facts")

    complete = {k: _plausible(k) for k in required}
    for omitted in required:
        partial = {k: v for k, v in complete.items() if k != omitted}
        decision = evaluate(workflow, context_for(workflow, Knowledge(partial)))
        assert decision.disposition not in AUTONOMOUS, (
            "{} acted without {}".format(workflow.category, omitted)
        )


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_unreachable_patient_never_yields_autonomous_action(workflow):
    """A loop that needs the patient cannot be closed without reaching them."""
    if not workflow.needs_patient_contact:
        pytest.skip("workflow does not require patient contact")

    unreachable = Patient(
        name=scenarios.PATIENT.name,
        mrn=scenarios.PATIENT.mrn,
        dob=scenarios.PATIENT.dob,
        sex=scenarios.PATIENT.sex,
        contact=Contact(phone="(415) 555-0148", verified_at=None),
        social_detail=scenarios.PATIENT.social_detail,
    )
    ctx = context_for(workflow, Knowledge(), patient=unreachable)
    assert evaluate(workflow, ctx).disposition not in AUTONOMOUS


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_gather_window_expiry_hands_off_rather_than_waiting(workflow):
    """A workflow that cannot establish its facts in time must escalate."""
    if workflow.gather_window is None:
        pytest.skip("no gather window")

    ctx = context_for(workflow)
    ctx.now = NOW + workflow.gather_window + timedelta(minutes=1)
    decision = evaluate(workflow, ctx)
    assert decision.escalates


# ---------------------------------------------------------------- guard shape


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_guards_only_ever_remove_permission(workflow):
    """Evaluate must never upgrade a workflow's own proposal to an action."""
    ctx = context_for(workflow)
    raw = workflow.decide(ctx)
    guarded = evaluate(workflow, ctx)
    if raw.disposition not in AUTONOMOUS:
        assert guarded.disposition not in AUTONOMOUS


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_every_disposition_is_classified(workflow):
    """No disposition may be neither gated nor permitted -- that would be a hole."""
    ctx = context_for(workflow)
    d = evaluate(workflow, ctx).disposition
    assert d in AUTONOMOUS or d in ALWAYS_PERMITTED


# ---------------------------------------------------------------- PHI, everywhere


@pytest.mark.parametrize("workflow", REGISTRY, ids=IDS)
def test_no_escalation_summary_leaks_identifiers(workflow):
    """Every workflow's page goes through the same scan, not just the culture one."""
    required = {k: _plausible(k) for k in workflow.required_facts()}
    ctx = context_for(workflow, Knowledge(required))
    summary = workflow.escalation_summary(ctx)
    assert scan(summary, scenarios.PATIENT) == [], summary


def _plausible(fact: str):
    """A value of the right shape for each declared fact."""
    return {
        "fever_or_chills": False,
        "flank_pain": False,
        "nausea_vomiting": False,
        "allergies_reconfirmed": [],
        "patient_reached": True,
        "symptoms_now": "settled, no chest pain",
        "willing_to_return": True,
        "preliminary_read": "no acute abnormality",
        "final_read": "no acute abnormality",
        "trajectory": "resolved",
        "pending_results_confirmed": True,
    }[fact]
