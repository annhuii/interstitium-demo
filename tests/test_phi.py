"""A page that leaks identifiers must never be emitted."""

import pytest

from interstitium import scenarios
from interstitium.phi import PHILeakError, compose, scan

PATIENT = scenarios.PATIENT
LINK = "https://ehr.example.org/enc/9f2a41"


def page():
    return compose(
        patient=PATIENT,
        encounter_when="Sat 2pm",
        clinical_summary=(
            "Culture is Escherichia coli, ESBL, ciprofloxacin-resistant, and she's now "
            "reporting fever + flank pain. Possible pyelonephritis."
        ),
        link=LINK,
    )


def test_page_carries_no_identifiers():
    assert scan(page().rendered(), PATIENT) == []


@pytest.mark.parametrize(
    "identifier",
    ["Danielle", "Tan", "4471029", "1979-03-14", "03/14/1979", "(415) 555-0148", "4155550148"],
)
def test_each_identifier_is_detected_if_present(identifier):
    leaky = "Follow-up on your ED patient {}. Please review.".format(identifier)
    assert scan(leaky, PATIENT), "failed to detect {}".format(identifier)


def test_phone_is_detected_despite_reformatting():
    assert scan("call 415-555-0148 now", PATIENT)
    assert scan("call 415.555.0148 now", PATIENT)


def test_compose_refuses_to_emit_a_leaky_message():
    with pytest.raises(PHILeakError):
        compose(
            patient=PATIENT,
            encounter_when="Sat 2pm",
            clinical_summary="Danielle Tan has a resistant organism.",
            link=LINK,
        )


def test_clinical_urgency_survives_minimisation():
    body = page().body
    for term in ("ESBL", "resistant", "fever", "flank pain", "pyelonephritis"):
        assert term.lower() in body.lower()


def test_social_detail_is_retained_for_recognition():
    assert "music teacher" in page().body


def test_identifiers_live_only_behind_the_link():
    p = page()
    assert p.link.startswith("https://")
    assert PATIENT.mrn not in p.rendered()
