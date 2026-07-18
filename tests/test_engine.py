"""End-to-end: the two branches the demo shows, plus the unreachable case."""

from dataclasses import replace

from interstitium import engine, scenarios
from interstitium.models import Contact, Status
from interstitium.policy import TherapyAction


def run(screen, patient=None):
    return engine.run(
        patient=patient or scenarios.PATIENT,
        culture=scenarios.CULTURE,
        screen=screen,
        current_agent=scenarios.EMPIRIC_AGENT,
    )


def test_clear_screen_closes_the_loop():
    r = run(scenarios.SCREEN_CLEAR)
    assert r.decision.disposition is TherapyAction.SWITCH_THERAPY
    assert r.item.status is Status.RESOLVED
    assert r.item.escalated is False
    assert r.page is None
    assert "nitrofurantoin" in r.render()


def test_red_flag_escalates_and_pages_without_prescribing():
    r = run(scenarios.SCREEN_RED_FLAG)
    assert r.decision.disposition is TherapyAction.ESCALATE
    assert r.item.status is Status.ESCALATED
    assert r.item.physician_notified is True
    assert r.page is not None
    trace = r.render().lower()
    assert "order transmitted" not in trace


def test_escalation_page_in_trace_carries_no_identifiers():
    from interstitium.phi import scan

    r = run(scenarios.SCREEN_RED_FLAG)
    assert scan(r.render(), scenarios.PATIENT) == []


def test_unverified_contact_cannot_own_a_follow_up():
    unreachable = replace(
        scenarios.PATIENT, contact=Contact(phone="(415) 555-0148", verified_at=None)
    )
    r = run(scenarios.SCREEN_CLEAR, patient=unreachable)
    assert r.item.status is Status.ESCALATED
    assert r.decision is None


def test_trace_is_deterministic():
    assert run(scenarios.SCREEN_RED_FLAG).render() == run(scenarios.SCREEN_RED_FLAG).render()
