"""A result that never came back.

Every other workflow is triggered by something happening. This one is triggered
by something *not* happening: the expected turnaround for an order elapsed and no
result ever arrived. That inverts the usual failure mode. A resistant culture at
least generates a result somebody could in principle read; a specimen that never
reached the laboratory generates nothing at all, so there is no queue it sits in,
no inbox it lands in, and nothing for a human to miss noticing. It is invisible
rather than merely unnoticed.

The clinically important part is that "no result" has several causes with
opposite responses, and they are not distinguishable without asking the lab:

  * the specimen never arrived            -> recollect; the patient must return
  * the specimen was rejected             -> recollect; someone was told, nobody acted
  * the result exists but never routed    -> the answer is sitting in the LIS
  * the assay is genuinely still running  -> wait, but keep the loop open

The third is the one that matters most and is easiest to miss: the laboratory
believes it did its job, the ordering system shows nothing pending, and the
result exists in a system nobody is looking at. Treating "no result in the chart"
as "no result produced" is how that gets buried.
"""

from datetime import timedelta
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


class LabResultIntegrityWorkflow(Workflow):
    category = "result_never_returned"
    urgency = Urgency.PRIORITY
    # Diagnosing this is a conversation with the laboratory, not the patient.
    # The patient is only involved once we know a recollection is needed.
    needs_patient_contact = False
    fact_source = FactSource.LABORATORY
    gather_window = timedelta(hours=12)

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        return signal.kind == "result_overdue"

    def required_facts(self) -> Tuple[str, ...]:
        return ("specimen_status", "result_available_in_lis")

    def decide(self, ctx: Context) -> Decision:
        order = ctx.signal.payload.get("order", "result")
        overdue_by = ctx.signal.payload.get("overdue_by", "expected turnaround")
        reasons = [
            "{} ordered at that visit has not returned; {} past {}".format(
                order, overdue_by, "expected turnaround"
            )
        ]

        missing = ctx.knowledge.missing(self.required_facts())
        if missing:
            return Decision(
                Disposition.GATHER_FACTS,
                reasons + ["cause of non-return not established: {}".format(", ".join(missing))],
                action="query laboratory: specimen receipt, accession status, result availability",
                urgency=Urgency.PRIORITY,
            )

        status = (ctx.fact("specimen_status") or "").lower()
        in_lis = ctx.fact("result_available_in_lis")

        # The interface failure. The result exists; only its delivery failed.
        if in_lis is True:
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                reasons
                + [
                    "result exists in the laboratory system but was never delivered "
                    "to the encounter -- delivery failure, not a laboratory delay",
                    "clinical content is available now and has never been reviewed",
                ],
                action="attach result to encounter and route for review; raise interface fault",
                urgency=Urgency.PRIORITY,
            )

        if status in ("never_received", "lost_in_transit"):
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                reasons
                + [
                    "specimen never reached the laboratory; no result will ever arrive",
                    "recollection required -- the patient must be brought back",
                ],
                action="request recollection; notify ordering clinician",
                urgency=Urgency.PRIORITY,
            )

        if status == "rejected":
            reason = ctx.fact("rejection_reason") or "not stated"
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                reasons
                + [
                    "specimen rejected by the laboratory ({}) and never recollected".format(reason),
                    "rejection was reported to a queue, not to an owner",
                ],
                action="request recollection; notify ordering clinician",
                urgency=Urgency.PRIORITY,
            )

        if status in ("in_progress", "received"):
            return Decision(
                Disposition.MONITOR,
                reasons + ["specimen received and assay still in progress; no fault found"],
                action="hold loop open; re-check at next expected interval",
            )

        # An unrecognised status is not a benign one.
        return Decision(
            Disposition.ESCALATE_CLINICIAN,
            reasons + ["laboratory reports an unrecognised specimen status: '{}'".format(status)],
            urgency=Urgency.PRIORITY,
        )

    def escalation_summary(self, ctx: Context) -> str:
        order = ctx.signal.payload.get("order", "a test")
        if ctx.fact("result_available_in_lis") is True:
            return (
                "{} from that visit resulted in the lab system but was never delivered "
                "to the record, so it has never been reviewed. Content is available now."
            ).format(order)
        status = ctx.fact("specimen_status") or "unknown"
        return (
            "{} from that visit never returned. Laboratory reports specimen status "
            "'{}'. No result is coming without a recollection."
        ).format(order, status)
