"""The demo encounter, as data. The HTML demo renders exactly this case."""

from datetime import date, datetime

from .models import Contact, CultureResult, Interp, Patient, SymptomScreen

COLLECTED = datetime(2026, 7, 18, 14, 40)
RESULTED = datetime(2026, 7, 20, 15, 2)

PATIENT = Patient(
    name="Danielle Tan",
    mrn="4471029",
    dob=date(1979, 3, 14),
    sex="F",
    contact=Contact(phone="(415) 555-0148", verified_at=datetime(2026, 7, 18, 14, 2)),
    allergies=[],
    pcp=None,
    social_detail="the music teacher, jazz trio, first-time UTI, sent home on cipro",
)

CULTURE = CultureResult(
    organism="Escherichia coli",
    esbl=True,
    colony_count=">100,000 CFU/mL",
    collected_at=COLLECTED,
    resulted_at=RESULTED,
    susceptibilities={
        "ampicillin": Interp.R,
        "ciprofloxacin": Interp.R,
        "levofloxacin": Interp.R,
        "ceftriaxone": Interp.R,
        "trimethoprim-sulfamethoxazole": Interp.R,
        "amoxicillin-clavulanate": Interp.I,
        "nitrofurantoin": Interp.S,
        "fosfomycin": Interp.S,
        "meropenem": Interp.S,
    },
)

EMPIRIC_AGENT = "ciprofloxacin"

# Stage 4, screen negative -- the agent switches therapy itself.
SCREEN_CLEAR = SymptomScreen(
    fever_or_chills=False,
    flank_pain=False,
    nausea_vomiting=False,
    ongoing_dysuria=True,
    allergies_reconfirmed=[],
    answered=True,
)

# Stage 4, red-flag branch -- the agent halts and pages the physician.
SCREEN_RED_FLAG = SymptomScreen(
    fever_or_chills=True,
    flank_pain=True,
    nausea_vomiting=True,
    ongoing_dysuria=True,
    allergies_reconfirmed=[],
    answered=True,
)

# The patient never picked up. Nothing is known -- so nothing is prescribed.
SCREEN_UNANSWERED = SymptomScreen()
