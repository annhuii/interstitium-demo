"""Run the follow-up loop and emit a trace.

The trace is the same event stream the demo UI renders, except here it is
computed from the inputs rather than scripted. Swap the culture or the screen
answers and the events change accordingly.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

from . import phi, policy
from .models import (
    CultureResult,
    FollowUpItem,
    Patient,
    Status,
    SymptomScreen,
)


class EventKind(str, Enum):
    SYSTEM = "SYSTEM"
    REASONING = "REASONING"
    ACTION = "ACTION"
    CALL = "CALL"
    ESCALATION = "ESCALATION"


@dataclass
class Event:
    kind: EventKind
    message: str
    at: Optional[datetime] = None

    def __str__(self) -> str:
        stamp = self.at.strftime("%H:%M") if self.at else "--:--"
        return "{}  {:<11} {}".format(stamp, self.kind.value, self.message)


@dataclass
class LoopResult:
    events: List[Event] = field(default_factory=list)
    decision: Optional[policy.Decision] = None
    item: Optional[FollowUpItem] = None
    page: Optional[phi.EscalationMessage] = None

    def render(self) -> str:
        return "\n".join(str(e) for e in self.events)


def new_follow_up_item() -> FollowUpItem:
    return FollowUpItem(
        category="pending_culture_empiric_therapy",
        instructions=(
            "Own the urine culture result. On resistance to empiric therapy, screen for "
            "upper-tract/systemic features, then switch to a susceptible oral agent or escalate."
        ),
        action_if_positive=(
            "Safety screen -> if clear, re-prescribe by susceptibility; "
            "if red flags, halt and page treating physician."
        ),
        action_if_negative="Confirm symptom resolution, close loop.",
    )


def run(
    patient: Patient,
    culture: CultureResult,
    screen: SymptomScreen,
    current_agent: str,
    treating_physician: str = "Dr. Lim",
    encounter_when: str = "Sat 2pm",
    secure_link: str = "https://ehr.example.org/enc/9f2a41",
    now: Optional[datetime] = None,
) -> LoopResult:
    now = now or culture.resulted_at
    item = new_follow_up_item()
    out = LoopResult(item=item)
    log = lambda kind, msg: out.events.append(Event(kind, msg, now))

    if not patient.contact.is_reachable:
        item.escalate("No verified contact point; loop cannot be closed by phone.")
        log(EventKind.ESCALATION, "No verified contact on file -- cannot own this follow-up.")
        return out

    log(
        EventKind.SYSTEM,
        "Culture resulted at {:.0f}h post-collection: {}{}.".format(
            culture.turnaround_hours,
            culture.organism,
            " (ESBL-positive)" if culture.esbl else "",
        ),
    )
    item.status = Status.ACTING

    decision = policy.decide(patient, culture, screen, current_agent)
    out.decision = decision
    for reason in decision.reasons:
        log(EventKind.REASONING, reason)

    if decision.disposition is policy.Disposition.NO_ACTION:
        item.resolve("Empiric therapy adequate on final susceptibilities.")
        log(EventKind.ACTION, "No therapy change required. Follow-up item resolved.")
        return out

    if decision.prescribes:
        log(
            EventKind.ACTION,
            "Discontinue {}. Order transmitted: {} {}.".format(
                current_agent, decision.agent, decision.dosing
            ),
        )
        log(EventKind.CALL, "Return precautions delivered; follow-up check scheduled +3 days.")
        item.resolve(
            "Therapy corrected to {} on susceptibility; loop remains open until symptom resolution.".format(
                decision.agent
            )
        )
        return out

    # Escalation path.
    log(EventKind.ESCALATION, "Halting autonomous prescribing. Paging {}.".format(treating_physician))

    # Only state symptoms the patient actually reported. An unanswered screen
    # defaults to the conservative worst case internally, but those defaults are
    # an absence of information -- reporting them as findings would page a
    # physician with symptoms nobody described.
    culture_part = "Culture is {}{}, {}-resistant.".format(
        culture.organism, ", ESBL" if culture.esbl else "", current_agent
    )
    if not screen.answered:
        clinical = (
            "{} Empiric therapy is ineffective and the patient could not be reached "
            "for a safety screen, so upper-tract involvement cannot be excluded."
        ).format(culture_part)
    else:
        clinical = "{} She's now reporting {}. Possible pyelonephritis.".format(
            culture_part, " + ".join(screen.red_flags)
        )

    page = phi.compose(
        patient=patient,
        encounter_when=encounter_when,
        clinical_summary=clinical,
        link=secure_link,
    )
    out.page = page
    log(EventKind.ESCALATION, "Page sent (identifiers stripped): {}".format(page.rendered()))

    item.escalate(
        "Halted autonomous prescribing; escalated to treating physician for suspected pyelonephritis."
    )
    log(EventKind.SYSTEM, "Follow-up item held open under physician ownership.")
    return out
