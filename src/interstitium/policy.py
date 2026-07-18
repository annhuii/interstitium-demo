"""The decision the loop exists to make: switch the antibiotic, or escalate.

Design rule: escalation is the default and prescribing is the exception. Every
gate below can only ever *remove* the option to prescribe autonomously. There is
no path where a missing answer, an unknown agent, or an empty candidate list
results in a prescription.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from . import formulary
from .models import CultureResult, Interp, Patient, Route, Site, SymptomScreen


class TherapyAction(str, Enum):
    NO_ACTION = "no_action"
    SWITCH_THERAPY = "switch_therapy"
    ESCALATE = "escalate"


@dataclass
class Decision:
    disposition: TherapyAction
    reasons: List[str] = field(default_factory=list)
    agent: Optional[str] = None
    dosing: Optional[str] = None
    considered: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)

    @property
    def prescribes(self) -> bool:
        return self.disposition is TherapyAction.SWITCH_THERAPY

    @property
    def escalates(self) -> bool:
        return self.disposition is TherapyAction.ESCALATE


def therapy_is_effective(culture: CultureResult, current_agent: str) -> bool:
    """Absence of a susceptibility result is not evidence of susceptibility."""
    return culture.interp(current_agent) is Interp.S


def oral_candidates(
    culture: CultureResult,
    site: Site,
    allergies: Optional[List[str]] = None,
    stock: Optional[frozenset] = None,
) -> List[str]:
    """Susceptible AND oral AND site-appropriate AND stocked AND not an allergen.

    Ordered by guideline preference, with local antibiogram as the tiebreak only
    within a rank -- see `formulary.FIRST_LINE_ORDER`.
    """
    allergen = {a.lower() for a in (allergies or [])}
    stocked = formulary.PHARMACY_STOCK if stock is None else stock

    out = []
    for agent in culture.agents_with(Interp.S):
        key = agent.lower()
        if key not in formulary.AGENTS:
            continue
        if formulary.profile(key).route is not Route.ORAL:
            continue
        if not formulary.treats_site(key, site):
            continue
        if key in allergen:
            continue
        if key not in stocked:
            continue
        out.append(key)

    return sorted(
        out,
        key=lambda a: (formulary.guideline_rank(a), -formulary.LOCAL_ANTIBIOGRAM.get(a, 0)),
    )


def decide(
    patient: Patient,
    culture: CultureResult,
    screen: SymptomScreen,
    current_agent: str,
) -> Decision:
    """Top-level gate. Returns the action the agent is permitted to take."""
    reasons: List[str] = []

    if therapy_is_effective(culture, current_agent):
        return Decision(
            TherapyAction.NO_ACTION,
            ["{} remains susceptible; current therapy is adequate".format(current_agent)],
        )

    interp = culture.interp(current_agent)
    reasons.append(
        "{} is {} against {} -- patient is on ineffective therapy".format(
            current_agent,
            interp.value if interp else "not reported",
            culture.organism,
        )
    )
    if culture.esbl:
        reasons.append("ESBL-positive isolate; beta-lactam options are constrained")

    # Gate 1 -- an unanswered screen cannot clear a patient.
    if not screen.answered:
        reasons.append("safety screen not completed; cannot exclude systemic involvement")
        return Decision(TherapyAction.ESCALATE, reasons)

    # Gate 2 -- systemic or upper-tract features are not an oral-swap situation.
    if screen.has_red_flags:
        reasons.append(
            "red flags present ({}); suspected upper-tract or systemic involvement".format(
                ", ".join(screen.red_flags)
            )
        )
        reasons.append("oral urinary-concentrating agents would undertreat; physician assessment required")
        return Decision(TherapyAction.ESCALATE, reasons)

    # Gate 3 -- allergies must be reconfirmed with the patient, not read from chart alone.
    allergies = screen.allergies_reconfirmed
    if allergies is None:
        reasons.append("drug allergies not reconfirmed with patient at time of prescribing")
        return Decision(TherapyAction.ESCALATE, reasons)

    site = screen.suspected_site
    candidates = oral_candidates(culture, site, allergies)

    # Gate 4 -- no acceptable oral agent means a human decides, not a fallback.
    if not candidates:
        reasons.append("no susceptible, stocked, site-appropriate oral agent available")
        return Decision(TherapyAction.ESCALATE, reasons, considered=candidates)

    chosen = candidates[0]
    reasons.append(
        "screen negative for systemic features; infection localised to {}".format(site.value)
    )
    reasons.append(
        "{} susceptible on isolate and {}% susceptible on local antibiogram".format(
            chosen, formulary.LOCAL_ANTIBIOGRAM.get(chosen, 0)
        )
    )
    return Decision(
        TherapyAction.SWITCH_THERAPY,
        reasons,
        agent=chosen,
        dosing=formulary.profile(chosen).dosing,
        considered=candidates,
        rejected=[a for a in culture.agents_with(Interp.S) if a not in candidates],
    )
