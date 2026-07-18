"""The safety properties. If one of these fails, the agent is not safe to run."""

import itertools

import pytest

from interstitium import scenarios
from interstitium.models import Interp, Site, SymptomScreen
from interstitium.policy import TherapyAction, decide, oral_candidates

PATIENT = scenarios.PATIENT
CULTURE = scenarios.CULTURE
EMPIRIC = scenarios.EMPIRIC_AGENT


def screen(**kw):
    base = dict(
        fever_or_chills=False,
        flank_pain=False,
        nausea_vomiting=False,
        allergies_reconfirmed=[],
        answered=True,
    )
    base.update(kw)
    return SymptomScreen(**base)


def test_resistant_empiric_therapy_is_detected():
    d = decide(PATIENT, CULTURE, screen(), EMPIRIC)
    assert d.disposition is not TherapyAction.NO_ACTION
    assert any("ineffective therapy" in r for r in d.reasons)


def test_clear_screen_switches_to_susceptible_oral_agent():
    d = decide(PATIENT, CULTURE, screen(), EMPIRIC)
    assert d.disposition is TherapyAction.SWITCH_THERAPY
    assert d.agent == "nitrofurantoin"
    assert CULTURE.interp(d.agent) is Interp.S


@pytest.mark.parametrize(
    "flags",
    [c for n in (1, 2, 3) for c in itertools.combinations(
        ["fever_or_chills", "flank_pain", "nausea_vomiting"], n)],
)
def test_any_red_flag_combination_never_prescribes(flags):
    """The core invariant: no red-flag state may produce a prescription."""
    d = decide(PATIENT, CULTURE, screen(**{f: True for f in flags}), EMPIRIC)
    assert d.disposition is TherapyAction.ESCALATE
    assert d.agent is None


def test_unanswered_screen_escalates_rather_than_assuming_no_fever():
    d = decide(PATIENT, CULTURE, SymptomScreen(), EMPIRIC)
    assert d.disposition is TherapyAction.ESCALATE
    assert any("not completed" in r for r in d.reasons)


def test_allergies_must_be_reconfirmed_live():
    d = decide(PATIENT, CULTURE, screen(allergies_reconfirmed=None), EMPIRIC)
    assert d.disposition is TherapyAction.ESCALATE
    assert any("not reconfirmed" in r for r in d.reasons)


def test_reported_allergy_removes_the_agent():
    d = decide(PATIENT, CULTURE, screen(allergies_reconfirmed=["nitrofurantoin"]), EMPIRIC)
    assert d.agent != "nitrofurantoin"


def test_urinary_only_agents_are_never_chosen_for_upper_tract():
    """Nitrofurantoin and fosfomycin do not reach renal tissue levels."""
    for site in (Site.UPPER, Site.UNKNOWN):
        assert oral_candidates(CULTURE, site, []) == []


def test_susceptible_but_unstocked_agent_is_not_recommended():
    got = oral_candidates(CULTURE, Site.LOWER, [], stock=frozenset({"fosfomycin"}))
    assert got == ["fosfomycin"]


def test_no_available_oral_agent_escalates():
    d = decide(PATIENT, CULTURE, screen(allergies_reconfirmed=["nitrofurantoin", "fosfomycin"]), EMPIRIC)
    assert d.disposition is TherapyAction.ESCALATE
    assert any("no susceptible" in r for r in d.reasons)


def test_effective_empiric_therapy_needs_no_change():
    d = decide(PATIENT, CULTURE, screen(), "nitrofurantoin")
    assert d.disposition is TherapyAction.NO_ACTION


def test_agent_absent_from_panel_is_not_assumed_susceptible():
    d = decide(PATIENT, CULTURE, screen(), "cefalexin")
    assert d.disposition is not TherapyAction.NO_ACTION


def test_guideline_preference_beats_a_marginal_antibiogram_edge():
    """Fosfomycin scores 97% locally vs nitrofurantoin's 96%, but first-line
    guidance -- not a one-point difference -- decides the order."""
    assert oral_candidates(CULTURE, Site.LOWER, []) == ["nitrofurantoin", "fosfomycin"]
