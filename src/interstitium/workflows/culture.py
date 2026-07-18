"""Pending culture that may defeat the empiric antibiotic.

The reference workflow: fully worked out, with its clinical reasoning in
`policy.py` and `formulary.py`. The others are deliberately thinner -- what they
demonstrate is that the interface holds, not that the medicine is complete.
"""

from datetime import timedelta
from typing import Tuple

from .. import policy
from ..models import SymptomScreen
from ..runtime import (
    Context,
    Decision,
    Disposition,
    Encounter,
    Signal,
    Urgency,
    Workflow,
)


class CultureResultWorkflow(Workflow):
    category = "pending_culture_empiric_therapy"
    urgency = Urgency.PRIORITY
    needs_patient_contact = True
    gather_window = timedelta(hours=24)

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        return signal.kind == "culture_resulted"

    def required_facts(self) -> Tuple[str, ...]:
        return ("fever_or_chills", "flank_pain", "nausea_vomiting", "allergies_reconfirmed")

    def decide(self, ctx: Context) -> Decision:
        culture = ctx.signal.payload["culture"]
        current = ctx.encounter.empiric_therapy

        # An unanswered screen is a reason to call the patient, not a reason to
        # page a physician. Escalating here would burn a clinician's attention on
        # a question the agent is capable of asking. If the call does not happen
        # inside the gather window, the runtime escalates on its own.
        missing = ctx.knowledge.missing(self.required_facts())
        if missing:
            return Decision(
                Disposition.GATHER_FACTS,
                [
                    "{} resistant to {}; therapy is ineffective".format(
                        culture.organism, current
                    ),
                    "safety screen required before any therapy change: {}".format(
                        ", ".join(missing)
                    ),
                ],
                action="outbound call: sepsis/pyelonephritis screen + allergy recheck",
                urgency=Urgency.PRIORITY,
            )

        screen = SymptomScreen(
            fever_or_chills=ctx.fact("fever_or_chills", True),
            flank_pain=ctx.fact("flank_pain", True),
            nausea_vomiting=ctx.fact("nausea_vomiting", True),
            allergies_reconfirmed=ctx.fact("allergies_reconfirmed"),
            answered=not ctx.knowledge.missing(self.required_facts()),
        )

        inner = policy.decide(ctx.patient, culture, screen, current)

        if inner.disposition is policy.TherapyAction.NO_ACTION:
            return Decision(Disposition.CLOSE_LOOP, inner.reasons, "empiric therapy adequate")
        if inner.disposition is policy.TherapyAction.SWITCH_THERAPY:
            return Decision(
                Disposition.CHANGE_THERAPY,
                inner.reasons,
                "{} {}".format(inner.agent, inner.dosing),
                urgency=Urgency.PRIORITY,
            )
        return Decision(Disposition.ESCALATE_CLINICIAN, inner.reasons, urgency=Urgency.PRIORITY)

    def escalation_summary(self, ctx: Context) -> str:
        culture = ctx.signal.payload["culture"]
        flags = [
            label
            for key, label in (
                ("fever_or_chills", "fever or chills"),
                ("flank_pain", "flank pain"),
            )
            if ctx.fact(key) is True
        ]
        base = "Culture is {}{}, {}-resistant.".format(
            culture.organism,
            ", ESBL" if culture.esbl else "",
            ctx.encounter.empiric_therapy,
        )
        if flags:
            return "{} She's now reporting {}. Possible pyelonephritis.".format(
                base, " + ".join(flags)
            )
        return "{} Safety screen incomplete, so upper-tract involvement cannot be excluded.".format(base)
