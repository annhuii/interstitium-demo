"""Agent properties, local antibiogram, and what the nearby pharmacy stocks.

Site eligibility is the clinically load-bearing part. Nitrofurantoin and
fosfomycin concentrate in urine and do not reach therapeutic tissue levels in
the kidney -- they treat cystitis and would undertreat pyelonephritis. Encoding
that as data (rather than hoping a policy author remembers it) is what lets
`policy.py` refuse to prescribe them for an upper-tract infection.
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet

from .models import Route, Site


@dataclass(frozen=True)
class AgentProfile:
    name: str
    route: Route
    treats: FrozenSet[Site]
    dosing: str = ""


_LOWER = frozenset({Site.LOWER})
_BOTH = frozenset({Site.LOWER, Site.UPPER})

AGENTS: Dict[str, AgentProfile] = {
    "nitrofurantoin": AgentProfile(
        "nitrofurantoin", Route.ORAL, _LOWER, "100 mg PO BID x 5 days"
    ),
    "fosfomycin": AgentProfile(
        "fosfomycin", Route.ORAL, _LOWER, "3 g PO x 1 dose"
    ),
    "ciprofloxacin": AgentProfile(
        "ciprofloxacin", Route.ORAL, _BOTH, "500 mg PO BID x 7 days"
    ),
    "levofloxacin": AgentProfile(
        "levofloxacin", Route.ORAL, _BOTH, "750 mg PO daily x 5 days"
    ),
    "trimethoprim-sulfamethoxazole": AgentProfile(
        "trimethoprim-sulfamethoxazole", Route.ORAL, _BOTH, "160/800 mg PO BID x 3 days"
    ),
    "amoxicillin-clavulanate": AgentProfile(
        "amoxicillin-clavulanate", Route.ORAL, _LOWER, "500/125 mg PO BID x 7 days"
    ),
    "ampicillin": AgentProfile("ampicillin", Route.ORAL, _LOWER),
    "ceftriaxone": AgentProfile("ceftriaxone", Route.IV, _BOTH, "1 g IV daily"),
    "meropenem": AgentProfile("meropenem", Route.IV, _BOTH, "1 g IV q8h"),
    "ertapenem": AgentProfile("ertapenem", Route.IV, _BOTH, "1 g IV daily"),
}

# Community urinary isolates, E. coli, trailing 12 months. Percent susceptible.
LOCAL_ANTIBIOGRAM: Dict[str, int] = {
    "nitrofurantoin": 96,
    "fosfomycin": 97,
    "ciprofloxacin": 64,
    "trimethoprim-sulfamethoxazole": 76,
    "ceftriaxone": 88,
}

# Guideline preference for uncomplicated cystitis, first-line first. Ranking on
# this rather than on antibiogram percentage is deliberate: a one-point
# difference in local susceptibility is noise, and letting it flip the choice
# would silently override guidance built on tolerability and collateral
# resistance. The antibiogram is a filter and a talking point, not the tiebreak.
FIRST_LINE_ORDER = (
    "nitrofurantoin",
    "fosfomycin",
    "trimethoprim-sulfamethoxazole",
    "amoxicillin-clavulanate",
)


def guideline_rank(agent: str) -> int:
    key = agent.lower()
    return FIRST_LINE_ORDER.index(key) if key in FIRST_LINE_ORDER else len(FIRST_LINE_ORDER)


# What the nearest pharmacy can actually dispense today. A recommendation the
# patient cannot collect is not a treatment.
PHARMACY_STOCK: FrozenSet[str] = frozenset(
    {"nitrofurantoin", "fosfomycin", "trimethoprim-sulfamethoxazole"}
)


def profile(agent: str) -> AgentProfile:
    key = agent.lower()
    if key not in AGENTS:
        raise KeyError("unknown antimicrobial agent: {}".format(agent))
    return AGENTS[key]


def treats_site(agent: str, site: Site) -> bool:
    """Unknown site is treated as upper tract -- the conservative reading."""
    effective = Site.UPPER if site is Site.UNKNOWN else site
    return effective in profile(agent).treats
