"""Scheduled symptom check after discharge.

Time-triggered rather than event-triggered: nothing external happened, the clock
simply reached day three. The judgement is about trajectory -- better, same, or
worse -- and 'same' is not the same as 'fine'.
"""

from datetime import timedelta
from typing import Tuple

from ..runtime import (
    Context,
    Decision,
    Disposition,
    Encounter,
    Signal,
    Urgency,
    Workflow,
)


class SymptomFollowUpWorkflow(Workflow):
    category = "post_discharge_symptom_check"
    urgency = Urgency.ROUTINE
    needs_patient_contact = True
    gather_window = timedelta(days=2)

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        return signal.kind == "symptom_check_due"

    def required_facts(self) -> Tuple[str, ...]:
        return ("trajectory",)

    def decide(self, ctx: Context) -> Decision:
        # Unknown is not a trajectory. Falling through to the "persists" branch
        # would report an absence of information as a clinical observation.
        if not ctx.knowledge.known("trajectory"):
            return Decision(
                Disposition.GATHER_FACTS,
                ["day {} check due; trajectory not yet established".format(
                    ctx.signal.payload.get("day", "?")
                )],
                action="contact patient for symptom trajectory",
            )

        trajectory = (ctx.fact("trajectory") or "").lower()

        if trajectory == "resolved":
            return Decision(
                Disposition.CLOSE_LOOP,
                ["symptoms resolved at day {}".format(ctx.signal.payload.get("day", "?"))],
                action="loop closed; no further contact scheduled",
            )

        if trajectory == "worse":
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                ["symptoms worse than at discharge despite treatment"],
                urgency=Urgency.PRIORITY,
            )

        # Unchanged is the interesting case. It is not deterioration, but it is
        # also not the expected trajectory, so the loop stays open rather than
        # being closed on a technicality.
        return Decision(
            Disposition.MONITOR,
            ["symptoms persist without improvement; loop stays open"],
            action="re-check in 48h; escalate if unchanged again",
        )

    def escalation_summary(self, ctx: Context) -> str:
        return (
            "Post-discharge check: symptoms reported as '{}' rather than improving "
            "on the treatment given at that visit."
        ).format(ctx.fact("trajectory") or "not established")
