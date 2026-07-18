"""Owner of last resort, so that no open loop is ever unowned.

Every specialised workflow encodes a condition someone anticipated. This one
exists for the ones nobody did: a signal type not yet modelled, a result from a
service that was integrated last week, a discharge that does not look like
anything in the registry.

It deliberately has no clinical opinion. It cannot close a loop and it cannot act
on one -- the only thing it does is refuse to let a loop disappear, by attaching
a human owner to it. That is the difference between "we handle five conditions"
and "no patient falls through": the unmodelled case degrades to a person rather
than to silence.
"""

from typing import Tuple

from ..runtime import (
    Context,
    Decision,
    Disposition,
    Encounter,
    FactSource,
    Signal,
    Urgency,
    Workflow,
)


class UnclassifiedLoopWorkflow(Workflow):
    category = "unclassified_open_loop"
    urgency = Urgency.ROUTINE
    needs_patient_contact = False
    fact_source = FactSource.RECORD_SYSTEM
    is_fallback = True

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        return True  # claims anything the specialists left behind

    def required_facts(self) -> Tuple[str, ...]:
        # It cannot know what it would need to know. That is precisely why it is
        # not permitted to act.
        return ()

    def decide(self, ctx: Context) -> Decision:
        return Decision(
            Disposition.ESCALATE_CLINICIAN,
            [
                "signal '{}' has no registered workflow".format(ctx.signal.kind),
                "no clinical policy exists for this loop; assigning a human owner "
                "rather than dropping it",
            ],
            action="route to clinician queue for triage",
            urgency=Urgency.ROUTINE,
        )

    def escalation_summary(self, ctx: Context) -> str:
        return (
            "An unresolved item from that visit ('{}') has no automated owner. "
            "Surfacing it rather than letting it lapse."
        ).format(ctx.signal.kind)
