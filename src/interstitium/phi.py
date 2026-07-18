"""Build a physician page that carries clinical urgency but no identifiers.

The message goes over a general-purpose chat channel (Teams, Slack), so it must
survive being screenshotted, forwarded, or read on a lock screen. The identifiers
live behind an authenticated EHR link; the message carries only the clinical
facts plus a memorable non-identifying detail, because that is how a clinician
who saw thirty patients that shift actually re-recognises this one.

`compose` refuses to return a message that fails its own scan. A leak is a bug
that raises, not a warning someone reads later.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import List

from .models import Patient


class PHILeakError(RuntimeError):
    """Raised when a message intended for an unsecured channel contains PHI."""


@dataclass(frozen=True)
class EscalationMessage:
    body: str
    link: str
    channel: str = "teams"

    def rendered(self) -> str:
        return "{} {}".format(self.body, self.link)


def _digit_runs(text: str) -> List[str]:
    """Digit sequences, tolerant of the separators phone numbers are written with.

    Collapsing every digit in the message into one string would be safer but
    creates false matches by concatenating unrelated numbers, so runs stop at
    ordinary prose.
    """
    runs = re.findall(r"\d[\d\s().\-]*", text)
    return [d for d in (re.sub(r"\D", "", r) for r in runs) if d]


def scan(text: str, patient: Patient) -> List[str]:
    """Return a list of PHI findings. Empty list means clean.

    Checks the identifiers we can enumerate for this patient: name tokens, MRN,
    date of birth in several renderings, and the phone number ignoring
    punctuation. This is a targeted scan for known values, not a general-purpose
    de-identifier -- it answers "did *this* patient's identifiers leak", which is
    the question that matters at send time.
    """
    findings: List[str] = []
    haystack = text.lower()
    runs = _digit_runs(text)

    # Word-boundary matching, not substring: a surname like "Tan" otherwise
    # matches inside "resistant" and blocks a perfectly clean clinical message.
    for token in patient.name.split():
        if len(token) < 3:
            continue
        if re.search(r"\b{}\b".format(re.escape(token.lower())), haystack):
            findings.append("name token: {}".format(token))

    # Identifier numbers are matched inside digit runs so that reformatting or
    # concatenation ("mrn4471029") cannot smuggle them past the scan.
    mrn_digits = re.sub(r"\D", "", patient.mrn or "")
    if mrn_digits and any(mrn_digits in run for run in runs):
        findings.append("MRN: {}".format(patient.mrn))

    dob = patient.dob
    dob_forms = {
        dob.isoformat(),
        dob.strftime("%m/%d/%Y"),
        dob.strftime("%d/%m/%Y"),
        dob.strftime("%d %b %Y").lower(),
        dob.strftime("%B %d, %Y").lower(),
        dob.strftime("%B %d").lower(),
    }
    for form in dob_forms:
        if form and form.lower() in haystack:
            findings.append("date of birth: {}".format(form))

    phone_digits = re.sub(r"\D", "", patient.contact.phone)
    if phone_digits and any(phone_digits in run for run in runs):
        findings.append("phone number")

    return findings


def compose(
    patient: Patient,
    encounter_when: str,
    clinical_summary: str,
    link: str,
    channel: str = "teams",
) -> EscalationMessage:
    """Assemble the page and refuse to emit it if it contains identifiers."""
    body = (
        "Follow-up on your ED patient from {when} -- {detail}. {clinical} "
        "Please review in EHR:"
    ).format(
        when=encounter_when,
        detail=patient.social_detail,
        clinical=clinical_summary.strip(),
    )

    findings = scan(body, patient)
    if findings:
        raise PHILeakError(
            "refusing to send: message contains {}".format("; ".join(findings))
        )

    return EscalationMessage(body=body, link=link, channel=channel)
