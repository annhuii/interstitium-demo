"""The autonomous runtime: what every follow-up workflow inherits.

A workflow supplies three things -- when it fires, what it must know before it
may act, and how it decides. Everything else is enforced here, once, for all of
them:

  * an autonomous action is impossible while any required fact is unknown
  * a workflow that needs to speak to the patient cannot run without a verified
    contact point
  * a workflow that cannot gather what it needs, in the time it has, escalates

The point of centralising this is that adding a sixth workflow does not mean
reimplementing the safety property and hoping it was got right. It means
declaring `required_facts()` and inheriting it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import FollowUpItem, Patient, Status


class Urgency(str, Enum):
    ROUTINE = "routine"
    PRIORITY = "priority"
    IMMEDIATE = "immediate"


class Disposition(str, Enum):
    """What the agent may do about an open loop."""

    MONITOR = "monitor"
    GATHER_FACTS = "gather_facts"
    CLOSE_LOOP = "close_loop"
    CHANGE_THERAPY = "change_therapy"
    BOOK_FOLLOWUP = "book_followup"
    ESCALATE_CLINICIAN = "escalate_clinician"
    ESCALATE_EMERGENCY = "escalate_emergency"


#: Dispositions that change the patient's care without a human in the loop.
#: These are the only ones gated on complete information.
AUTONOMOUS = frozenset(
    {Disposition.CLOSE_LOOP, Disposition.CHANGE_THERAPY, Disposition.BOOK_FOLLOWUP}
)

#: Reaching out to the patient is how facts get gathered, so it is never gated
#: on already having them. Escalation is never gated at all -- a workflow must
#: always be able to hand off, especially when it knows nothing.
ALWAYS_PERMITTED = frozenset(
    {
        Disposition.MONITOR,
        Disposition.GATHER_FACTS,
        Disposition.ESCALATE_CLINICIAN,
        Disposition.ESCALATE_EMERGENCY,
    }
)


class UNKNOWN:
    """Sentinel for a fact that has not been established."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "UNKNOWN"


@dataclass(frozen=True)
class Knowledge:
    """Facts established about this loop. Absence means unknown, never False.

    Presence is what marks a fact as known, so an answer of `False` ("no fever")
    is information, while a missing key is not. Collapsing those two is the
    mistake that lets an unanswered screen read as a negative one.
    """

    facts: Dict[str, Any] = field(default_factory=dict)

    def known(self, key: str) -> bool:
        return key in self.facts and not isinstance(self.facts[key], UNKNOWN)

    def get(self, key: str, default: Any = None) -> Any:
        value = self.facts.get(key, default)
        return default if isinstance(value, UNKNOWN) else value

    def missing(self, keys: Iterable[str]) -> List[str]:
        return [k for k in keys if not self.known(k)]

    def having(self, **kw: Any) -> "Knowledge":
        merged = dict(self.facts)
        merged.update(kw)
        return Knowledge(merged)


@dataclass(frozen=True)
class Signal:
    """Something that happened after discharge and may reopen the plan."""

    kind: str
    at: datetime
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Encounter:
    id: str
    patient: Patient
    discharged_at: datetime
    disposition: str = "home"          # home | ama | admitted
    problems: List[str] = field(default_factory=list)
    pending_results: List[str] = field(default_factory=list)
    empiric_therapy: Optional[str] = None
    acuity: int = 3                    # ESI
    ordering_clinician: str = "Dr. Lim"

    @property
    def left_ama(self) -> bool:
        return self.disposition == "ama"


@dataclass
class Context:
    encounter: Encounter
    signal: Signal
    knowledge: Knowledge = field(default_factory=Knowledge)
    now: Optional[datetime] = None

    @property
    def patient(self) -> Patient:
        return self.encounter.patient

    @property
    def elapsed(self) -> timedelta:
        return (self.now or self.signal.at) - self.signal.at

    def fact(self, key: str, default: Any = None) -> Any:
        return self.knowledge.get(key, default)


@dataclass
class Decision:
    disposition: Disposition
    reasons: List[str] = field(default_factory=list)
    action: Optional[str] = None
    urgency: Urgency = Urgency.ROUTINE

    @property
    def is_autonomous(self) -> bool:
        return self.disposition in AUTONOMOUS

    @property
    def escalates(self) -> bool:
        return self.disposition in (
            Disposition.ESCALATE_CLINICIAN,
            Disposition.ESCALATE_EMERGENCY,
        )


class FactSource(str, Enum):
    """Where a workflow's missing facts have to come from.

    Not everything is established by phoning the patient. A lab integrity check
    interrogates the laboratory system; a report diff reads the RIS. Getting this
    wrong means the runtime blocks a workflow for lacking a phone number it never
    needed.
    """

    PATIENT = "patient"
    LABORATORY = "laboratory"
    RECORD_SYSTEM = "record_system"


class Workflow(ABC):
    """One kind of open loop. Supplies its own gates; inherits the guards."""

    category: str = "unnamed"
    urgency: Urgency = Urgency.ROUTINE

    #: Whether closing this loop involves speaking with the patient. If so, an
    #: unverified contact point is disqualifying.
    needs_patient_contact: bool = True

    #: Where this workflow gets what it does not know.
    fact_source: FactSource = FactSource.PATIENT

    #: A fallback owns signals no specialised workflow claims. Exactly one
    #: should be registered; see `route`.
    is_fallback: bool = False

    #: How long the workflow may spend trying to establish its facts before it
    #: must hand off. None means no deadline.
    gather_window: Optional[timedelta] = None

    @abstractmethod
    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        """Does this workflow own this signal for this encounter?"""

    @abstractmethod
    def required_facts(self) -> Tuple[str, ...]:
        """Facts that must be established before any autonomous action."""

    @abstractmethod
    def decide(self, ctx: Context) -> Decision:
        """Workflow-specific reasoning. May assume nothing about completeness."""

    @abstractmethod
    def escalation_summary(self, ctx: Context) -> str:
        """Clinical text for the physician page. Must contain no identifiers."""

    def new_item(self) -> FollowUpItem:
        return FollowUpItem(
            category=self.category,
            instructions=self.__doc__ or "",
            action_if_positive="escalate to treating clinician",
            action_if_negative="close loop",
        )


# --------------------------------------------------------------------------
# guards -- the part no workflow can opt out of
# --------------------------------------------------------------------------


def evaluate(workflow: Workflow, ctx: Context) -> Decision:
    """Run a workflow's own reasoning, then constrain it.

    Guards can only ever move a decision *away* from autonomous action. No guard
    upgrades a decision, so no combination of guards can invent permission to
    act that the workflow itself did not propose.
    """
    decision = workflow.decide(ctx)

    if decision.escalates:
        return decision  # already handing off; nothing left to constrain

    missing = ctx.knowledge.missing(workflow.required_facts())
    overdue = workflow.gather_window is not None and ctx.elapsed > workflow.gather_window
    reachable = ctx.patient.contact.is_reachable

    # Liveness. This is checked before the always-permitted shortcut because
    # MONITOR and GATHER_FACTS are the dispositions a loop can quietly rot in:
    # both are safe to return forever, and a loop that stays open forever while
    # nobody is told is the exact failure this system exists to prevent. Once the
    # window is spent and the facts are still unknown, a human is told.
    if missing and overdue:
        return Decision(
            Disposition.ESCALATE_CLINICIAN,
            decision.reasons
            + [
                "{} still not established after {}".format(
                    ", ".join(missing), workflow.gather_window
                ),
                "handing off: gather window elapsed",
            ],
            urgency=max_urgency(workflow.urgency, decision.urgency),
        )

    if decision.disposition in ALWAYS_PERMITTED:
        return decision

    if missing and decision.is_autonomous:
        note = "cannot act autonomously: {} not established".format(", ".join(missing))

        # Only patient-sourced facts are blocked by an unreachable patient. A lab
        # integrity check does not need a phone number to query the laboratory.
        if workflow.fact_source is FactSource.PATIENT and not reachable:
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                decision.reasons + [note, "handing off: no verified contact point"],
                urgency=max_urgency(workflow.urgency, decision.urgency),
            )

        return Decision(
            Disposition.GATHER_FACTS,
            decision.reasons + [note],
            action="query {} to establish: {}".format(
                workflow.fact_source.value, ", ".join(missing)
            ),
            urgency=decision.urgency,
        )

    if workflow.needs_patient_contact and not ctx.patient.contact.is_reachable:
        return Decision(
            Disposition.ESCALATE_CLINICIAN,
            decision.reasons + ["no verified contact point; loop cannot be closed by phone"],
            urgency=max_urgency(workflow.urgency, decision.urgency),
        )

    return decision


_ORDER = {Urgency.ROUTINE: 0, Urgency.PRIORITY: 1, Urgency.IMMEDIATE: 2}


def max_urgency(a: Urgency, b: Urgency) -> Urgency:
    return a if _ORDER[a] >= _ORDER[b] else b


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------


@dataclass
class Outcome:
    workflow: Workflow
    decision: Decision
    item: FollowUpItem

    def __str__(self) -> str:
        return "{:<28} {:<20} {}".format(
            self.workflow.category,
            self.decision.disposition.value,
            self.decision.action or (self.decision.reasons[-1] if self.decision.reasons else ""),
        )


def route(
    encounter: Encounter, signal: Signal, registry: Sequence[Workflow]
) -> List[Workflow]:
    """Every signal gets an owner. Specialists first, fallback if none claim it.

    The alternative -- returning an empty list -- means an unrecognised signal is
    silently dropped, which is the failure this whole system exists to prevent.
    A loop nobody owns is exactly as dangerous whether it went unowned because no
    human noticed it or because no workflow matched it.
    """
    specialists = [
        w for w in registry if not w.is_fallback and w.triggered_by(encounter, signal)
    ]
    if specialists:
        return specialists
    return [w for w in registry if w.is_fallback and w.triggered_by(encounter, signal)]


def handle(
    encounter: Encounter,
    signal: Signal,
    registry: Sequence[Workflow],
    knowledge: Optional[Knowledge] = None,
    now: Optional[datetime] = None,
) -> List[Outcome]:
    """Route a signal to every workflow that owns it and evaluate each."""
    ctx = Context(encounter, signal, knowledge or Knowledge(), now)
    outcomes = []
    for workflow in route(encounter, signal, registry):
        decision = evaluate(workflow, ctx)
        item = workflow.new_item()
        if decision.escalates:
            item.escalate(decision.reasons[-1] if decision.reasons else "escalated")
        elif decision.disposition is Disposition.CLOSE_LOOP:
            item.resolve(decision.action or "loop closed")
        else:
            item.status = Status.ACTING
        outcomes.append(Outcome(workflow, decision, item))
    return outcomes
