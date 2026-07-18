"""Drive every registered workflow from a signal, and print what it decided.

    python -m interstitium --registry

Each block is one signal arriving after discharge. Note that nothing here is
scripted: the dispositions come from the same guards the tests assert over.
"""

from datetime import datetime, timedelta
from typing import List, Tuple

from . import scenarios
from .runtime import Encounter, Knowledge, Signal, handle
from .workflows import REGISTRY

DISCHARGED = datetime(2026, 7, 18, 15, 10)
LATER = datetime(2026, 7, 20, 15, 2)


def _encounter(**kw) -> Encounter:
    base = dict(
        id="enc-4471029-1",
        patient=scenarios.PATIENT,
        discharged_at=DISCHARGED,
        disposition="home",
        problems=["acute uncomplicated cystitis"],
        pending_results=["urine culture"],
        empiric_therapy="ciprofloxacin",
    )
    base.update(kw)
    return Encounter(**base)


def cases() -> List[Tuple[str, Encounter, Signal, Knowledge, datetime]]:
    return [
        (
            "discharge, open loops, agent takes ownership",
            _encounter(),
            Signal("discharge", DISCHARGED),
            Knowledge({"pending_results_confirmed": True}),
            DISCHARGED,
        ),
        (
            "culture returns resistant, screen clear -> agent switches therapy",
            _encounter(),
            Signal("culture_resulted", LATER, {"culture": scenarios.CULTURE}),
            Knowledge(
                {
                    "fever_or_chills": False,
                    "flank_pain": False,
                    "nausea_vomiting": False,
                    "allergies_reconfirmed": [],
                }
            ),
            LATER,
        ),
        (
            "culture returns resistant, fever + flank -> escalates",
            _encounter(),
            Signal("culture_resulted", LATER, {"culture": scenarios.CULTURE}),
            Knowledge(
                {
                    "fever_or_chills": True,
                    "flank_pain": True,
                    "nausea_vomiting": False,
                    "allergies_reconfirmed": [],
                }
            ),
            LATER,
        ),
        (
            "culture returns, patient not yet screened -> gathers, does not act",
            _encounter(),
            Signal("culture_resulted", LATER, {"culture": scenarios.CULTURE}),
            Knowledge(),
            LATER,
        ),
        (
            "AMI patient left AMA -> two owners, immediate",
            _encounter(disposition="ama", problems=["acute myocardial infarction"]),
            Signal("discharge", DISCHARGED),
            Knowledge({"pending_results_confirmed": True}),
            DISCHARGED,
        ),
        (
            "AMI AMA, unreachable for 3h -> hands off rather than waiting",
            _encounter(disposition="ama", problems=["acute myocardial infarction"]),
            Signal("discharge", DISCHARGED),
            Knowledge({"pending_results_confirmed": True}),
            DISCHARGED + timedelta(hours=3),
        ),
        (
            "radiology addendum introduces a nodule -> escalates to ordering clinician",
            _encounter(),
            Signal("report_amended", LATER),
            Knowledge(
                {
                    "preliminary_read": "no acute abnormality",
                    "final_read": "8mm pulmonary nodule, recommend CT follow-up",
                }
            ),
            LATER,
        ),
        (
            "day 3 symptom check, resolved -> loop closed",
            _encounter(),
            Signal("symptom_check_due", LATER, {"day": 3}),
            Knowledge({"trajectory": "resolved"}),
            LATER,
        ),
        (
            "low-risk discharge, nothing pending -> closed at intake",
            _encounter(
                patient=_with_pcp(),
                pending_results=[],
                empiric_therapy=None,
                problems=["ankle sprain"],
            ),
            Signal("discharge", DISCHARGED),
            Knowledge({"pending_results_confirmed": True}),
            DISCHARGED,
        ),
    ]


def _with_pcp():
    from dataclasses import replace

    return replace(scenarios.PATIENT, pcp="Dr. Okafor")


def main() -> None:
    for label, encounter, signal, knowledge, now in cases():
        print("\n--- {}".format(label))
        print("    signal: {}".format(signal.kind))
        outcomes = handle(encounter, signal, REGISTRY, knowledge, now=now)
        if not outcomes:
            print("    (no workflow owns this signal)")
        for o in outcomes:
            print("    {}".format(o))
            for reason in o.decision.reasons[-2:]:
                print("        - {}".format(reason))
    print()


if __name__ == "__main__":
    main()
