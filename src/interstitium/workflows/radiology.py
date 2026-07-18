"""Radiology report amended after the patient went home.

The distinguishing feature is that the trigger is a *diff*, not a value: the
preliminary read said one thing, the final read says another, and the question is
whether the change alters management. The patient may not need to be contacted at
all -- this loop is often closed clinician-to-clinician.
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

#: Findings that change management even when the patient feels well.
ACTIONABLE = (
    "pulmonary embolism",
    "pneumothorax",
    "mass",
    "nodule",
    "fracture",
    "aneurysm",
    "abscess",
    "obstruction",
    "malignancy",
)


class RadiologyAddendumWorkflow(Workflow):
    category = "radiology_report_changed"
    urgency = Urgency.PRIORITY
    # This one can be closed without the patient: the ordering clinician is the
    # counterparty. An unreachable patient does not block the handoff.
    needs_patient_contact = False

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        return signal.kind in ("report_amended", "report_finalised")

    def required_facts(self) -> Tuple[str, ...]:
        return ("preliminary_read", "final_read")

    def decide(self, ctx: Context) -> Decision:
        # Two unknown reads are not two matching reads. Without this the
        # workflow would propose closing the loop on an encounter it knows
        # nothing about -- the runtime would block it, but proposing it at all
        # is the bug.
        missing = ctx.knowledge.missing(self.required_facts())
        if missing:
            return Decision(
                Disposition.MONITOR,
                ["report versions not yet retrieved: {}".format(", ".join(missing))],
                action="fetch preliminary and final reads",
            )

        prelim = (ctx.fact("preliminary_read") or "").lower()
        final = (ctx.fact("final_read") or "").lower()

        if prelim == final:
            return Decision(
                Disposition.CLOSE_LOOP,
                ["final read matches preliminary; discharge plan unaffected"],
                action="no change to management",
            )

        new_findings = [term for term in ACTIONABLE if term in final and term not in prelim]
        if new_findings:
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                [
                    "final read differs from the preliminary read the discharge was based on",
                    "new actionable finding: {}".format(", ".join(new_findings)),
                ],
                urgency=Urgency.PRIORITY,
            )

        return Decision(
            Disposition.MONITOR,
            ["read changed but no actionable finding introduced; holding loop open for review"],
        )

    def escalation_summary(self, ctx: Context) -> str:
        return (
            "Imaging from that visit has been amended since discharge. Preliminary read "
            "was '{}'; final read is '{}'. Discharge plan was made on the preliminary."
        ).format(ctx.fact("preliminary_read"), ctx.fact("final_read"))
