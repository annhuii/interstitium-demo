"""Core data model for a post-discharge follow-up loop.

Nothing here is clever. The point is that the objects an ED discharge actually
produces -- a culture, a contact number, an allergy list -- become first-class
values that a policy can be run against, instead of prose in a chart that a
human has to notice.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional


class Interp(str, Enum):
    """Susceptibility interpretation from the micro lab."""

    S = "S"
    I = "I"
    R = "R"


class Route(str, Enum):
    ORAL = "oral"
    IV = "iv"


class Site(str, Enum):
    """Anatomic site of infection. Drives which agents are even eligible."""

    LOWER = "lower_urinary_tract"
    UPPER = "upper_urinary_tract"
    UNKNOWN = "unknown"


class Status(str, Enum):
    OPEN = "open"
    ACTING = "acting"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class Contact:
    """A reachable contact point, plus proof that it was reachable.

    `verified_at` is the whole point: an unverified number is not a follow-up
    plan. For patients without a stable address this may be a shelter or clinic
    callback line rather than a personal mobile.
    """

    phone: str
    verified_at: Optional[datetime] = None
    kind: str = "mobile"

    @property
    def is_reachable(self) -> bool:
        return self.verified_at is not None


@dataclass
class Patient:
    name: str
    mrn: str
    dob: date
    sex: str
    contact: Contact
    allergies: List[str] = field(default_factory=list)
    pcp: Optional[str] = None
    # A non-identifying detail clinicians actually re-recognise patients by.
    # Deliberately separate from `name`/`mrn` so it can survive PHI stripping.
    social_detail: str = ""

    def age_on(self, when: date) -> int:
        years = when.year - self.dob.year
        if (when.month, when.day) < (self.dob.month, self.dob.day):
            years -= 1
        return years

    @property
    def has_pcp(self) -> bool:
        return bool(self.pcp)

    @property
    def nkda(self) -> bool:
        """No known drug allergies."""
        return not self.allergies


@dataclass
class CultureResult:
    organism: str
    susceptibilities: Dict[str, Interp]
    collected_at: datetime
    resulted_at: datetime
    specimen: str = "urine, clean catch"
    colony_count: Optional[str] = None
    esbl: bool = False

    def interp(self, agent: str) -> Optional[Interp]:
        return self.susceptibilities.get(agent.lower())

    def agents_with(self, interp: Interp) -> List[str]:
        return sorted(a for a, i in self.susceptibilities.items() if i is interp)

    @property
    def turnaround_hours(self) -> float:
        return (self.resulted_at - self.collected_at).total_seconds() / 3600.0


@dataclass
class SymptomScreen:
    """Answers to the safety questions asked before any therapy change.

    Every red-flag field defaults to True (worst case). An unanswered screen is
    therefore never mistaken for a negative screen -- silence must not read as
    'no fever'.
    """

    fever_or_chills: bool = True
    flank_pain: bool = True
    nausea_vomiting: bool = True
    ongoing_dysuria: bool = False
    allergies_reconfirmed: Optional[List[str]] = None
    answered: bool = False

    RED_FLAG_LABELS = {
        "fever_or_chills": "fever or chills",
        "flank_pain": "flank or back pain",
        "nausea_vomiting": "nausea or vomiting",
    }

    @property
    def red_flags(self) -> List[str]:
        return [
            label
            for attr, label in self.RED_FLAG_LABELS.items()
            if getattr(self, attr)
        ]

    @property
    def has_red_flags(self) -> bool:
        return bool(self.red_flags)

    @property
    def suspected_site(self) -> Site:
        if not self.answered:
            return Site.UNKNOWN
        if self.fever_or_chills or self.flank_pain:
            return Site.UPPER
        return Site.LOWER


@dataclass
class FollowUpItem:
    """The agent's unit of work. One open loop, one owner, one outcome."""

    category: str
    instructions: str
    action_if_positive: str
    action_if_negative: str
    status: Status = Status.OPEN
    outcome: Optional[str] = None
    physician_notified: bool = False
    escalated: bool = False

    def escalate(self, outcome: str) -> "FollowUpItem":
        self.status = Status.ESCALATED
        self.escalated = True
        self.physician_notified = True
        self.outcome = outcome
        return self

    def resolve(self, outcome: str) -> "FollowUpItem":
        self.status = Status.RESOLVED
        self.outcome = outcome
        return self
