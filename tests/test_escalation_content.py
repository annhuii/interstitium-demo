"""A page must describe what actually happened, not what the defaults say.

The screen defaults every red flag to True so that silence never reads as
"no fever". That is right internally and wrong to repeat outward: an unanswered
screen means symptoms are unknown, not present.
"""

from interstitium import engine, scenarios


def page_for(screen):
    return engine.run(
        patient=scenarios.PATIENT,
        culture=scenarios.CULTURE,
        screen=screen,
        current_agent=scenarios.EMPIRIC_AGENT,
    ).page


def test_unanswered_screen_does_not_claim_reported_symptoms():
    body = page_for(scenarios.SCREEN_UNANSWERED).body.lower()
    assert "reporting" not in body
    assert "could not be reached" in body


def test_unanswered_screen_still_conveys_the_clinical_problem():
    body = page_for(scenarios.SCREEN_UNANSWERED).body.lower()
    assert "ciprofloxacin-resistant" in body
    assert "cannot be excluded" in body


def test_red_flag_page_reports_only_the_flags_actually_present():
    from interstitium.models import SymptomScreen

    only_fever = SymptomScreen(
        fever_or_chills=True,
        flank_pain=False,
        nausea_vomiting=False,
        allergies_reconfirmed=[],
        answered=True,
    )
    body = page_for(only_fever).body.lower()
    assert "fever or chills" in body
    assert "flank" not in body
