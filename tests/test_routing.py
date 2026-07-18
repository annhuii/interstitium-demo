"""Routing, and the liveness property: no loop may stall silently."""

from datetime import datetime, timedelta

import pytest

from interstitium import scenarios
from interstitium.runtime import (
    Context,
    Disposition,
    Encounter,
    Knowledge,
    Signal,
    evaluate,
    handle,
    route,
)
from interstitium.workflows import REGISTRY, SymptomFollowUpWorkflow

NOW = datetime(2026, 7, 20, 15, 0)


def enc(**kw):
    base = dict(
        id="enc-1",
        patient=scenarios.PATIENT,
        discharged_at=datetime(2026, 7, 18, 15, 10),
        disposition="home",
        problems=[],
        pending_results=[],
        empiric_therapy=None,
    )
    base.update(kw)
    return Encounter(**base)


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("culture_resulted", {"pending_culture_empiric_therapy"}),
        ("report_amended", {"radiology_report_changed"}),
        ("symptom_check_due", {"post_discharge_symptom_check"}),
    ],
)
def test_signals_route_to_the_owning_workflow(kind, expected):
    matched = route(enc(), Signal(kind, NOW), REGISTRY)
    assert {w.category for w in matched} == expected


def test_discharge_routes_to_intake_only_for_a_routine_discharge():
    matched = route(enc(), Signal("discharge", NOW), REGISTRY)
    assert {w.category for w in matched} == {"discharge_open_loop_screen"}


def test_high_risk_ama_discharge_routes_to_both_intake_and_ama():
    """One signal, two owners -- the runtime fans out rather than picking one."""
    encounter = enc(disposition="ama", problems=["acute myocardial infarction"])
    matched = route(encounter, Signal("discharge", NOW), REGISTRY)
    assert {w.category for w in matched} == {"discharge_open_loop_screen", "high_risk_ama"}


def test_low_risk_discharge_with_no_open_loops_closes_immediately():
    encounter = enc(patient=_with_pcp())
    outcomes = handle(
        encounter,
        Signal("discharge", NOW),
        REGISTRY,
        Knowledge({"pending_results_confirmed": True}),
        now=NOW,
    )
    assert [o.decision.disposition for o in outcomes] == [Disposition.CLOSE_LOOP]


def test_unrecognised_signal_matches_nothing_rather_than_guessing():
    assert route(enc(), Signal("lab_addendum_v2", NOW), REGISTRY) == []


def test_monitoring_cannot_continue_indefinitely():
    """The hole this test was written for: MONITOR is always permitted, so a
    workflow could return it forever and the loop would never surface."""
    workflow = SymptomFollowUpWorkflow()
    signal = Signal("symptom_check_due", NOW, {"day": 3})

    inside = Context(enc(), signal, Knowledge(), NOW + timedelta(hours=1))
    assert evaluate(workflow, inside).disposition is Disposition.GATHER_FACTS

    past = Context(enc(), signal, Knowledge(), NOW + workflow.gather_window + timedelta(hours=1))
    assert evaluate(workflow, past).escalates


def test_a_known_trajectory_may_monitor_past_the_window():
    """Deliberate monitoring on full information is not a stalled loop."""
    workflow = SymptomFollowUpWorkflow()
    signal = Signal("symptom_check_due", NOW, {"day": 3})
    ctx = Context(
        enc(),
        signal,
        Knowledge({"trajectory": "unchanged"}),
        NOW + workflow.gather_window + timedelta(hours=1),
    )
    assert evaluate(workflow, ctx).disposition is Disposition.MONITOR


def _with_pcp():
    from dataclasses import replace

    return replace(scenarios.PATIENT, pcp="Dr. Okafor")
