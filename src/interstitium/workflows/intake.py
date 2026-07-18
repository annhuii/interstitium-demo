"""Every discharge, screened for open loops.

This is not a follow-up workflow; it is the thing that decides whether any are
needed. It runs on every discharge and answers one question: does this encounter
leave anything unresolved that nobody owns?

Closing a loop here is a real decision, not a default. That is why it declares
required facts of its own -- an encounter whose pending results are unknown
cannot be certified as having none.
"""

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


class DischargeIntakeWorkflow(Workflow):
    category = "discharge_open_loop_screen"
    urgency = Urgency.ROUTINE
    # Screening the chart does not require reaching the patient. Acting on what
    # it finds generally does -- that is the next workflow's problem.
    needs_patient_contact = False

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        return signal.kind == "discharge"

    def required_facts(self) -> Tuple[str, ...]:
        return ("pending_results_confirmed",)

    def decide(self, ctx: Context) -> Decision:
        enc = ctx.encounter
        open_loops = []

        if enc.pending_results:
            open_loops.append("pending results: {}".format(", ".join(enc.pending_results)))
        if enc.empiric_therapy:
            open_loops.append("empiric therapy started: {}".format(enc.empiric_therapy))
        if not enc.patient.has_pcp:
            open_loops.append("no PCP on file -- no downstream owner")
        if enc.left_ama:
            open_loops.append("left against medical advice")

        if not open_loops:
            return Decision(
                Disposition.CLOSE_LOOP,
                ["no pending results, no empiric therapy, downstream owner exists"],
                action="no follow-up required",
            )

        # Something is unresolved. Assigning an owner is the action; deciding the
        # medicine belongs to whichever workflow the later signal routes to.
        if not enc.patient.contact.is_reachable:
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                open_loops + ["no verified contact point to close these with"],
                urgency=Urgency.PRIORITY,
            )

        return Decision(
            Disposition.BOOK_FOLLOWUP,
            open_loops,
            action="assign agent as follow-up owner ({} open loop(s))".format(len(open_loops)),
        )

    def escalation_summary(self, ctx: Context) -> str:
        return (
            "Discharge from that visit has unresolved items and no reachable contact "
            "point, so no follow-up owner could be assigned."
        )
