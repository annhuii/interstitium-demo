"""High-risk patient who left against medical advice.

The shape furthest from the culture case, which is why it is the useful second
workflow. It is triggered by the discharge itself rather than by a result, the
clock runs in hours rather than days, and the escalation target may be emergency
services rather than a chat message to an attending.

Note what this workflow can never do: there is no disposition it returns that
closes the loop on a patient it has not reached. An AMI patient who does not
answer the phone is escalated, not marked resolved.
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

#: Conditions where leaving AMA carries a short-fuse risk of deterioration.
HIGH_RISK = {
    "acute myocardial infarction",
    "ami",
    "chest pain, acs ruled in",
    "asthma exacerbation",
    "copd exacerbation",
    "gi bleed",
    "dka",
}


class HighRiskAMAWorkflow(Workflow):
    category = "high_risk_ama"
    urgency = Urgency.IMMEDIATE
    needs_patient_contact = True
    # Hours, not days. If the patient cannot be reached inside the window, that
    # is itself the finding, and it goes to a human.
    gather_window = timedelta(hours=2)

    def triggered_by(self, encounter: Encounter, signal: Signal) -> bool:
        if signal.kind != "discharge":
            return False
        if not encounter.left_ama:
            return False
        return any(p.lower() in HIGH_RISK for p in encounter.problems)

    def required_facts(self) -> Tuple[str, ...]:
        return ("patient_reached", "symptoms_now", "willing_to_return")

    def decide(self, ctx: Context) -> Decision:
        problems = ", ".join(ctx.encounter.problems)
        reasons = ["left AMA with {} -- short-fuse deterioration risk".format(problems)]

        # A known failure to reach the patient is a finding and escalates at once.
        if ctx.fact("patient_reached") is False:
            return Decision(
                Disposition.ESCALATE_CLINICIAN,
                reasons + ["patient not reachable after AMA discharge"],
                urgency=Urgency.IMMEDIATE,
            )

        # Not having tried yet is not a finding. Try -- but on a two-hour fuse,
        # after which the runtime hands off whether or not contact succeeded.
        missing = ctx.knowledge.missing(self.required_facts())
        if missing:
            return Decision(
                Disposition.GATHER_FACTS,
                reasons + ["post-AMA status not established: {}".format(", ".join(missing))],
                action="urgent outbound call: current symptoms + willingness to return",
                urgency=Urgency.IMMEDIATE,
            )

        symptoms = (ctx.fact("symptoms_now") or "").lower()
        if any(w in symptoms for w in ("chest pain", "short of breath", "worse", "syncope")):
            return Decision(
                Disposition.ESCALATE_EMERGENCY,
                reasons + ["ongoing or worsening symptoms reported after AMA: {}".format(symptoms)],
                action="advise immediate return; dispatch EMS if unable to self-present",
                urgency=Urgency.IMMEDIATE,
            )

        if ctx.fact("willing_to_return") is True:
            return Decision(
                Disposition.BOOK_FOLLOWUP,
                reasons + ["patient willing to return; securing earliest slot"],
                action="book urgent review",
                urgency=Urgency.IMMEDIATE,
            )

        # Distinguish "said no" from "never asked". Both escalate, but only one
        # of them may be reported to a clinician as a refusal.
        if ctx.knowledge.known("willing_to_return"):
            note = "patient declines return; clinician judgement required"
        else:
            note = "willingness to return not established"
        return Decision(
            Disposition.ESCALATE_CLINICIAN,
            reasons + [note],
            urgency=Urgency.IMMEDIATE,
        )

    def escalation_summary(self, ctx: Context) -> str:
        return (
            "Left AMA earlier today with {}. Post-discharge contact: {}. "
            "Not safe for the agent to close this loop."
        ).format(
            ", ".join(ctx.encounter.problems),
            ctx.fact("symptoms_now") or "not established",
        )
